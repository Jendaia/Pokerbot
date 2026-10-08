from __future__ import annotations

import argparse
from itertools import islice
import json
from typing import Iterator, Sequence

from ..calculators.combinations import (
    combination_counts, iter_complete_deals, possible_board_runouts,
    possible_next_boards, possible_opponent_hands,
)
from ..calculators.equity import EquityCalculator
from ..calculators.hand_distribution import HandDistributionCalculator
from ..calculators.methods import DEFAULT_MAX_EXACT_TRIALS
from ..core.cards import parse_cards
from ..core.game_state import GameState
from ..core.hand_evaluator import best_five, category_name, evaluate
from ..core.showdown import showdown
from ..models.results import EquityResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Texas Hold'em combinations and showdown probabilities")
    parser.add_argument("--hero", required=True, help='Two hole cards, e.g. "As Kh"')
    parser.add_argument("--board", default="", help="0, 3, 4, or 5 community cards")
    parser.add_argument("--opponents", type=int, default=1, help="Number of opponent seats, from 1 to 9")
    parser.add_argument(
        "--villain", action="append", default=[],
        help='Known cards for consecutive opponent seats; repeat, using "" for an unknown seat',
    )
    parser.add_argument("--dead", default="", help="Known unavailable cards, including exposed folded cards")
    parser.add_argument("--mode", choices=("auto", "exact", "monte-carlo"), default="auto")
    parser.add_argument("--simulations", type=int, default=100_000)
    parser.add_argument("--seed", type=int, help="Reproduce a Monte Carlo estimate")
    parser.add_argument("--max-exact-trials", type=int, default=DEFAULT_MAX_EXACT_TRIALS)
    parser.add_argument("--allow-large-exact", action="store_true", help="Allow exhaustive calculations above the trial limit")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--counts-only", action="store_true", help="Count every possibility without evaluating hands")
    operation.add_argument("--distribution-only", action="store_true", help="Calculate hero hand categories over board runouts")
    operation.add_argument(
        "--list", choices=("runouts", "next-boards", "opponents", "deals", "showdowns"),
        help="Stream combinations as JSON Lines; showdowns also includes outcome labels",
    )
    parser.add_argument("--limit", type=int, default=25, help="Maximum listing rows; 0 exports every combination")
    parser.add_argument("--seat", type=int, default=1, help="One-based opponent seat for --list opponents")
    return parser


def _rows(state: GameState, kind: str, seat: int) -> Iterator[dict[str, object]]:
    if kind == "runouts":
        for runout in possible_board_runouts(state):
            yield {"runout": [str(c) for c in runout], "board": [str(c) for c in state.board + runout]}
    elif kind == "next-boards":
        for board in possible_next_boards(state):
            yield {"board": [str(c) for c in board]}
    elif kind == "opponents":
        for hand in possible_opponent_hands(state, seat - 1):
            yield {"seat": seat, "hand": [str(c) for c in hand]}
    else:
        for deal in iter_complete_deals(state):
            row = {"hero": [str(c) for c in state.hero], **deal.as_dict()}
            if kind == "showdowns":
                winners = showdown((state.hero, *deal.opponent_hands), deal.board)
                rank = evaluate((*state.hero, *deal.board))
                row.update({
                    "winner_seats": winners,
                    "hero_pot_share": 1.0 / len(winners) if 0 in winners else 0.0,
                    "hero_hand": category_name(rank),
                    "hero_rank": rank,
                })
            yield row


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        state = GameState(
            hero=parse_cards(args.hero), board=parse_cards(args.board), opponents=args.opponents,
            opponent_hands=tuple(parse_cards(hand) for hand in args.villain),
            dead_cards=parse_cards(args.dead),
        )
        if args.limit < 0:
            raise ValueError("limit must be nonnegative; use 0 to list everything")
        if args.list:
            if args.list == "opponents" and not 1 <= args.seat <= state.opponents:
                raise ValueError("seat must be between 1 and the opponent count")
            rows = _rows(state, args.list, args.seat)
            for row in rows if args.limit == 0 else islice(rows, args.limit):
                print(json.dumps(row))
            return 0

        payload: dict[str, object] = {"state": state.as_dict(), "combinations": combination_counts(state)}
        if state.board:
            current = (*state.hero, *state.board)
            payload["current_hand"] = {
                "category": category_name(evaluate(current)),
                "rank": evaluate(current),
                "best_five": [str(c) for c in best_five(current)],
            }
        result = None
        if not args.counts_only:
            calculator = HandDistributionCalculator if args.distribution_only else EquityCalculator
            result = calculator(max_exact_trials=args.max_exact_trials).calculate(
                state, mode=args.mode, simulations=args.simulations, seed=args.seed,
                allow_large_exact=args.allow_large_exact,
            )
            payload.update(result.as_dict())
            payload["seed"] = args.seed
        if args.json:
            print(json.dumps(payload, indent=2, allow_nan=False))
            return 0

        counts = combination_counts(state)
        print(f"Street:          {state.street}")
        print(f"Hero:            {' '.join(str(c) for c in state.hero)}")
        print(f"Board:           {' '.join(str(c) for c in state.board) or '(none)'}")
        print(f"Opponents:       {state.opponents}")
        for seat, hand in enumerate(state.opponent_hands, 1):
            if hand:
                print(f"Opponent {seat}:      {' '.join(str(c) for c in hand)}")
        if state.dead_cards:
            print(f"Dead cards:      {' '.join(str(c) for c in state.dead_cards)}")
        if state.board:
            print(f"Current hand:    {category_name(evaluate((*state.hero, *state.board)))}")
        print(f"Board runouts:   {counts['board_runouts']:,}")
        print(f"Possible deals:  {counts['complete_deals']:,}")
        if result is None:
            return 0
        print(f"Method:          {result.mode}")
        print(f"Trials checked:  {result.trials:,}")
        if isinstance(result, EquityResult):
            print(f"Win outright:    {result.win_percentage:8.4f}%")
            print(f"Tie for best:    {result.tie_percentage:8.4f}%")
            print(f"Loss:            {result.loss_percentage:8.4f}%")
            print(f"Pot equity:      {result.equity_percentage:8.4f}%")
            if result.mode == "monte-carlo":
                low, high = result.equity_95_interval
                print(f"95% equity bound: [{low:.4f}%, {high:.4f}%] (Hoeffding)")
            print("Opponent model:  uniform legal holdings; every player reaches showdown")
        print("Hero final hands:")
        for name, percentage in sorted(result.category_percentages().items(), key=lambda item: -item[1]):
            print(f"  {name:<18} {percentage:8.4f}%")
        return 0
    except ValueError as error:
        parser.error(str(error))
    return 2
