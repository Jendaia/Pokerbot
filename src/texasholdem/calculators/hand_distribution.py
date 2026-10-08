from __future__ import annotations

from collections import Counter
import random

from ..core.game_state import GameState
from ..core.hand_evaluator import HAND_NAMES, _evaluate_unchecked
from ..models.results import HandDistributionResult
from .combinations import count_board_runouts, possible_board_runouts, unseen_cards
from .methods import DEFAULT_MAX_EXACT_TRIALS, select_method, validate_exact_limit


class HandDistributionCalculator:
    """Calculate final hero hand categories over all legal future board combinations."""

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
    ) -> HandDistributionResult:
        total = count_board_runouts(state)
        selected = select_method(mode, total, self.max_exact_trials, simulations, allow_large_exact)
        if selected == "exact":
            runouts = possible_board_runouts(state)
        else:
            rng = random.Random(seed)
            unseen = unseen_cards(state)
            runouts = (tuple(rng.sample(unseen, state.missing_board_cards)) for _ in range(simulations))
        categories: Counter[str] = Counter()
        trials = 0
        for runout in runouts:
            rank = _evaluate_unchecked((*state.hero, *state.board, *runout))
            categories[HAND_NAMES[rank[0]]] += 1
            trials += 1
        return HandDistributionResult(selected, total, trials, dict(categories))
