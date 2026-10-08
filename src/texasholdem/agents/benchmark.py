"""Offline, reproducible diagnostics. This module never imports game input."""
from __future__ import annotations

import argparse
import json
from math import sqrt
from pathlib import Path
import random
import statistics
import time

from ..analyzers.native.controls import ControlButton, ControlFrame
from ..core.cards import full_deck, parse_cards
from ..core.hand_evaluator import _evaluate_unchecked
from ..models.observation import ObservedCard, ObservedPlayer, TableObservation
from .models import Action, BotSettings
from .opponents import HandTracker
from .pots import pot_payout
from .search.betting import BettingState
from .search.ranges import range_space
from .search.river import RiverSolver
from .search.rollout import hand_equity_proxy
from .strategy import HybridPolicy


def river_benchmark(iterations=400):
    rows = []
    for text in ("Ks 7c 4d 2h 9s", "Qh Jh Th 2c 6d", "As Ad 8c 7h 2s", "9c 8c 7c 6c 2d"):
        space = range_space(parse_cards(text))
        for facing in (0, 100):
            state = BettingState((1, 2), (1000., 1000. - facing), (0., float(facing)), (100., 100. + facing),
                                 (False, False), frozenset({0} if facing else {0, 1}),
                                 frozenset({0} if facing else {0, 1}), 0, 1, 5, max(20, facing), 20)
            prior = space.strengths
            # Deliberately asymmetric ranges; fixed weights, no data fitting.
            solver = RiverSolver(state, space, [.2 + prior, .1 + prior ** 3], state.actions(), cap=1000)
            initial = solver.gap()["nash_conv_chips"]
            start = time.monotonic()
            solver.solve(iterations)
            result = solver.gap()
            rows.append({"board": text, "facing": facing, "initial_gap_chips": initial,
                         **result, "iterations": solver.iterations, "nodes": solver.nodes,
                         "seconds": time.monotonic() - start,
                         "utility_accounting_error": sum(result["profile_values"]) - state.pot})
    return {"benchmark": "restricted-river-convergence", "version": 1, "results": rows,
            "caveat": "Exact best responses inside the restricted river trees and supplied ranges; not full-game exploitability or a win-rate test."}


def observed_cards(cards):
    return tuple(ObservedCard(0, card.suit, str(card.rank), str(card)) for card in cards)


def observation(state, holes, board, hand_number):
    # The policy receives ONLY seat 0's hole cards, just like the native reader.
    players = tuple(ObservedPlayer(i + 1, f"Seat {i + 1}", i + 1, state.stacks[i], state.bets[i],
                                   state.folded[i], False, True, 2, i == 0) for i in range(len(holes)))
    return TableObservation("offline", 0, 1, hand_number, "Texas", "offline", False, 0,
                            tuple(range(1, len(holes) + 1)), state.button + 1, state.actor + 1,
                            players, observed_cards(board[:state.board_len]), 1, observed_cards(holes[0]),
                            int(state.pot - sum(state.bets)), sum(state.bets), int(state.big_blind / 2),
                            not state.terminal, state.terminal)


def opponent_action(state, hand, board, style, rng):
    """Fixed held-out scripts. None use tracked ranges or hidden cards."""
    menu = state.actions()
    passive = next((a for a in menu if a.kind in ("check", "call")), menu[0])
    raises = [a for a in menu if a.kind == "raise"]
    if style == "station":
        return passive
    equity = hand_equity_proxy(hand, board[:state.board_len], rng, samples=24)
    odds = state.call / max(1, state.pot + state.call)
    if style == "tight":
        if state.call and equity < max(.52, odds + .18):
            return Action("fold")
        return raises[0] if raises and equity > .8 else passive
    if state.call and equity < odds and rng.random() > .3:
        return Action("fold")
    return rng.choice(raises) if raises and rng.random() < .4 else passive


def arena_hand(strategy, seed, number, players, style, samples, seconds):
    rng = random.Random(seed * 1000003 + number)
    deck = list(full_deck()); rng.shuffle(deck)
    holes = [tuple(deck[2*i:2*i+2]) for i in range(players)]
    board = tuple(deck[players * 2:players * 2 + 5])
    button = number % players
    sb = button if players == 2 else (button + 1) % players
    bb = (sb + 1) % players
    bets = tuple(5. if i == sb else 10. if i == bb else 0. for i in range(players))
    state = BettingState(tuple(range(1, players + 1)), tuple(1000. - b for b in bets), bets, bets,
                         (False,) * players, frozenset(range(players)), frozenset(range(players)),
                         (bb + 1) % players, button, 0, 10, 10)
    tracker = HandTracker()
    tracker.observe(observation(state, holes, board, number), number)
    policy = HybridPolicy()
    settings = BotSettings(samples=samples, think_seconds=seconds, max_action_chips=1000, strategy=strategy)
    decisions, elapsed = 0, 0.
    for turn in range(256):
        if state.terminal:
            ranks = {state.ids[i]: _evaluate_unchecked((*holes[i], *board)) for i in state.live}
            value = pot_payout(dict(zip(state.ids, state.committed)), ranks, 1) - state.committed[0]
            return value / 10, decisions, elapsed
        if state.actor == 0:
            menu = state.actions()
            sizes = tuple(a.amount for a in menu if a.kind == "raise")
            buttons = tuple(ControlButton(k, k, True, (1, 1, 5, 5)) for k in dict.fromkeys(a.kind for a in menu))
            frame = ControlFrame(observation(state, holes, board, number), number, True, buttons, (100, 100),
                                 bool(sizes), min(sizes) if sizes else None, max(sizes) if sizes else None,
                                 min(sizes) if sizes else None, raise_steps=sizes)
            decision = policy.decide(frame, tracker, settings, seed=seed * 99991 + number * 101 + turn)
            action = decision.action
            decisions += 1; elapsed += decision.elapsed_seconds
        else:
            # Common randomness per public actor/street/turn across both runs;
            # branches may diverge, but the deck/button/opponent stay paired.
            opponent_rng = random.Random(seed * 99991 + number * 101 + turn)
            action = opponent_action(state, holes[state.actor], board, style, opponent_rng)
        state = state.apply(action)
        tracker.observe(observation(state, holes, board, number), number)
    raise ValueError("Arena hand did not terminate")


def arena_benchmark(hands=12, seeds=(11, 29, 47), players=3, samples=200, seconds=.2, candidate="hybrid"):
    rows = []
    start = time.monotonic()
    for seed in seeds:
        for number in range(hands):
            # Each archetype gets a full button orbit; don't confound style
            # with hero position by using hand % 3 at a three-player table.
            style = ("station", "tight", "aggressive")[(number // players) % 3]
            result = {}
            for policy in ("rollout", candidate):
                value, decisions, elapsed = arena_hand(policy, seed, number, players, style, samples, seconds)
                result[policy] = {"bb": value, "decisions": decisions, "decision_seconds": elapsed}
            rows.append({"seed": seed, "hand": number, "opponent": style, **result,
                         "difference_bb": result[candidate]["bb"] - result["rollout"]["bb"]})
        print(f"Completed seed {seed}: {len(rows)} paired hands", flush=True)
    diffs = [r["difference_bb"] for r in rows]
    mean = statistics.mean(diffs)
    # Report raw paired outcomes and SE; no significance claim from a short
    # smoke match or dependent hands sharing an opponent model.
    se = statistics.stdev(diffs) / sqrt(len(diffs)) if len(diffs) > 1 else None
    return {"benchmark": "paired-scripted-arena", "version": 2, "players": players, "candidate": candidate,
            "hands_per_policy": len(rows), "samples": samples, "seconds_per_decision": seconds,
            "paired_mean_bb_per_hand": mean, "paired_standard_error": se,
            "total_seconds": time.monotonic() - start, "results": rows,
            "caveat": "Offline cold-start comparison, not evidence of professional strength. Same shuffled deals; full button orbits per opponent style; profiles reset each hand; no rake. Time bounds can change trial counts across machines. Longer matches and strong external opponents are needed."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("river", "arena"))
    parser.add_argument("--iterations", type=int, default=400)
    parser.add_argument("--hands", type=int, default=12, help="paired hands per seed")
    parser.add_argument("--seeds", default="11,29,47")
    parser.add_argument("--players", type=int, choices=range(2, 10), default=3)
    parser.add_argument("--samples", type=int, default=200)
    parser.add_argument("--seconds", type=float, default=.2)
    parser.add_argument("--strategy", choices=("hybrid", "search"), default="hybrid", help="candidate to compare against the original rollout")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.iterations < 1 or args.hands < 1:
            raise ValueError("iterations and hands must be positive")
        BotSettings.from_dict({"samples": args.samples, "think_seconds": args.seconds})
        seeds = tuple(int(s) for s in args.seeds.split(","))
        result = river_benchmark(args.iterations) if args.mode == "river" else arena_benchmark(args.hands, seeds, args.players, args.samples, args.seconds, args.strategy)
    except ValueError as error:
        parser.error(str(error))
    text = json.dumps(result, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"Results: {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
