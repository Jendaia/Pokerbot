from __future__ import annotations

import random
import time

import numpy as np

from ...core.cards import full_deck
from ...core.hand_evaluator import _evaluate_unchecked
from ..models import Decision
from ..opponents import OpponentProfile
from ..pots import pot_payout
from .betting import BettingState, native_actions
from .ranges import JointSampler, range_space, response_distribution


def hand_equity_proxy(hand, board, rng, samples=12):
    """Cheap rollout feature using only this actor's cards and the public board.

    Future board samples here are independent of the episode's actual future
    board. Never use showdown rank on that future board to decide a flop bet.
    The feature uses a uniform opponent, not the full multiway belief model.
    """
    deck = [c for c in full_deck() if c not in (*hand, *board)]
    total = 0.
    for _ in range(samples):
        cards = rng.sample(deck, 2 + 5 - len(board))
        runout = (*board, *cards[2:])
        ours = _evaluate_unchecked((*hand, *runout))
        theirs = _evaluate_unchecked((*cards[:2], *runout))
        total += (ours > theirs) + .5 * (ours == theirs)
    # Shrink the small MC sample, avoiding certainty from twelve lucky draws.
    return (total + 1) / (samples + 2)


def continuation(state, hands, board, hero, tracker, cap, rng, features, feature_seed, style, cancelled=lambda: False):
    """Play all remaining streets using public-information response policies."""
    start = state.committed[hero]
    for step in range(256):
        if step % 8 == 0 and cancelled():
            raise ValueError("Decision was cancelled")
        if state.terminal:
            ranks = {state.ids[i]: _evaluate_unchecked((*hands[i], *board)) for i in state.live}
            payout = pot_payout(dict(zip(state.ids, state.committed)), ranks, state.ids[hero])
            return payout - (state.committed[hero] - start)
        actor = state.actor
        visible = tuple(board[:state.board_len])
        key = (actor, visible)
        if key not in features:
            # Stable per actor/street and shared between candidate branches.
            probe = random.Random(feature_seed + actor * 1009 + state.board_len * 9176)
            features[key] = hand_equity_proxy(hands[actor], visible, probe)
        profile = tracker.profiles.get(state.ids[actor], OpponentProfile())
        strength = max(.01, min(.99, features[key] + (style if actor != hero else 0)))
        odds = state.call / max(1, state.pot + state.call)
        fold, call, raise_ = response_distribution(strength, odds, len(state.live) - 1, profile)
        menu = state.actions(cap=cap if actor == hero else float("inf"))
        weights = []
        nraises = sum(a.kind == "raise" for a in menu)
        for action in menu:
            if action.kind == "fold":
                weights.append(fold)
            elif action.kind in ("call", "check"):
                weights.append(call + (raise_ if not nraises else 0))
            else:
                weights.append(raise_ / nraises)
        action = rng.choices(menu, weights=weights, k=1)[0]
        state = state.apply(action)
    raise ValueError("Continuation did not terminate within its action bound")


class MultiStreetPolicy:
    name = "Multi-street range rollout v2"

    def decide(self, frame, tracker, settings, cancelled=lambda: False, *, seed=None, started=None):
        started = time.monotonic() if started is None else started
        o = frame.observation
        gs = o.to_game_state()
        if o.acting_player_id != o.hero_id or not frame.legal:
            raise ValueError("The hero does not have a legal turn")
        actions = native_actions(frame, tracker, settings)
        if not tracker.ledger_complete:
            return Decision(actions[0], "Waiting for a complete hand ledger; check/fold only", 0., 0., 0,
                            time.monotonic() - started, (), "ledger-guard")
        state = BettingState.from_frame(frame, tracker)
        hero = state.actor
        opponents = [i for i in state.live if i != hero]
        space = range_space(gs.board)
        sampler = JointSampler(space, [space.weights(tracker, state.ids[i]) for i in opponents], gs.hero)
        rng = random.Random(seed)
        values = []
        styles = []
        equity = 0.
        deadline = started + settings.think_seconds
        attempts = 0
        while len(values) < settings.samples and time.monotonic() < deadline:
            if cancelled():
                raise ValueError("Decision was cancelled")
            sampled = sampler.sample(rng, cancelled)
            attempts += 1
            if sampled is None:
                continue
            hands = {hero: gs.hero, **dict(zip(opponents, sampled))}
            used = {*gs.hero, *gs.board, *(c for hand in sampled for c in hand)}
            board = (*gs.board, *rng.sample([c for c in full_deck() if c not in used], 5 - len(gs.board)))
            ranks = {i: _evaluate_unchecked((*hand, *board)) for i, hand in hands.items()}
            best = max(ranks.values())
            equity += (1 / sum(rank == best for rank in ranks.values())) if ranks[hero] == best else 0.
            roll_seed = rng.getrandbits(64)
            # Test three nearby population models on balanced sample counts.
            style = (0., -.08, .08)[len(values) % 3]
            styles.append(style)
            features, row = {}, []
            for action in actions:
                after = state.apply(action)
                cost = after.committed[hero] - state.committed[hero]
                if action.kind == "fold":
                    row.append(0.)
                else:
                    row.append(continuation(after, hands, board, hero, tracker, settings.max_action_chips,
                                            random.Random(roll_seed), features, roll_seed, style, cancelled) - cost)
            values.append(row)
        if cancelled():
            raise ValueError("Decision was cancelled")
        count = len(values)
        if count == 0:
            return Decision(actions[0], "Compute budget exhausted; use the available check/fold", 0., 0., 0,
                            time.monotonic() - started, (), "multi-street-rollout")
        matrix = np.array(values)
        means = matrix.mean(axis=0)
        errors = matrix.std(axis=0, ddof=1) / np.sqrt(count) if count > 1 else np.zeros(len(actions))
        paired = matrix - matrix[:, :1]
        paired_error = paired.std(axis=0, ddof=1) / np.sqrt(count) if count > 1 else np.zeros(len(actions))
        # Compare paired differences to the passive action; common deals remove
        # much of the showdown noise. This is a model-based estimate, not GTO.
        scores = means - means[0] - 1.64 * paired_error
        # A single noisy episode cannot justify spending chips.
        chosen = int(np.argmax(scores)) if count >= 24 else 0
        candidates = tuple({"action": a.kind, "amount": a.amount, "ev_chips": float(means[i]),
                            "standard_error": float(errors[i]), "paired_standard_error": float(paired_error[i]),
                            "score": float(scores[i]), "probability": float(i == chosen)} for i, a in enumerate(actions))
        model_means = [matrix[np.array(styles) == style].mean(axis=0) for style in sorted(set(styles))]
        spread = float(np.ptp(np.array(model_means)[:, chosen]))
        return Decision(actions[chosen], f"{actions[chosen].kind.title()} · future betting and counter-raises simulated · {count:,} shared deals",
                        equity / count, state.call / max(1, state.pot + state.call), count,
                        time.monotonic() - started, candidates, "multi-street-rollout",
                        {"model_spread_chips": spread, "joint_draw_attempts": attempts,
                         "history_actions": len(tracker.public_actions), "continuation": "three heuristic population models",
                         "limitations": "Estimated ranges and continuation policies; no equilibrium guarantee"})
