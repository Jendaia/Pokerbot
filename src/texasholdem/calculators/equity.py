from __future__ import annotations

from collections import Counter

from ..core.cards import Card
from ..core.game_state import GameState
from ..core.hand_evaluator import HAND_NAMES, HandRank, _evaluate_unchecked
from ..core.showdown import winning_seats
from ..models.results import EquityResult
from .combinations import count_complete_deals, iter_complete_deals
from .methods import DEFAULT_MAX_EXACT_TRIALS, select_method, validate_exact_limit
from .sampling import sample_deals


class EquityCalculator:
    """Showdown equity against uniform legal opponent holdings.

    Every opponent reaches the showdown. Tied pots are divided equally.
    Betting actions, rake, folds, and unequal contributions are not modeled.
    """

    def __init__(self, *, max_exact_trials: int = DEFAULT_MAX_EXACT_TRIALS) -> None:
        validate_exact_limit(max_exact_trials)
        self.max_exact_trials = max_exact_trials

    def calculate(
        self,
        state: GameState,
        *,
        mode: str = "auto",
        simulations: int = 100_000,
        seed: int | None = None,
        allow_large_exact: bool = False,
    ) -> EquityResult:
        total = count_complete_deals(state)
        selected = select_method(mode, total, self.max_exact_trials, simulations, allow_large_exact)
        deals = iter_complete_deals(state) if selected == "exact" else sample_deals(state, simulations, seed)
        result = EquityResult(mode=selected, total_possible=total)
        categories: Counter[str] = Counter()
        previous_board: tuple[Card, ...] | None = None
        opponent_cache: dict[tuple[Card, ...], HandRank] = {}
        hero_rank: HandRank = ()

        for deal in deals:
            # Exact deals are grouped by board. Cache only the current board's
            # ranks, so memory use never grows with the full search space.
            if deal.board != previous_board:
                previous_board = deal.board
                hero_rank = _evaluate_unchecked((*state.hero, *deal.board))
                opponent_cache.clear()
            opponent_ranks = []
            for hand in deal.opponent_hands:
                rank = opponent_cache.get(hand)
                if rank is None:
                    rank = _evaluate_unchecked((*hand, *deal.board))
                    opponent_cache[hand] = rank
                opponent_ranks.append(rank)
            winners = winning_seats((hero_rank, *opponent_ranks))
            share = 1.0 / len(winners) if 0 in winners else 0.0
            result.trials += 1
            categories[HAND_NAMES[hero_rank[0]]] += 1
            if 0 not in winners:
                result.losses += 1
            elif len(winners) == 1:
                result.wins += 1
            else:
                result.ties += 1
            result.equity_share += share
            result.equity_squared_share += share * share

        result.hand_categories = {name: categories[name] for name in HAND_NAMES}
        return result
