"""Reusable Texas Hold'em combinations, hand evaluation, and equity engine."""

from .calculators.combinations import (
    combination_counts, count_board_runouts, count_complete_deals,
    iter_complete_deals, possible_board_runouts, possible_hole_cards,
    possible_next_boards, possible_opponent_hands, unseen_cards,
)
from .calculators.equity import EquityCalculator
from .calculators.hand_distribution import HandDistributionCalculator
from .calculators.sampling import sample_deals
from .core.cards import Card, full_deck, parse_cards
from .core.game_state import GameState
from .core.hand_evaluator import best_five, category_name, evaluate, evaluate_five
from .core.showdown import showdown
from .models.deals import Deal
from .models.results import EquityResult, HandDistributionResult

__all__ = [
    "Card", "Deal", "EquityCalculator", "EquityResult", "GameState",
    "HandDistributionCalculator", "HandDistributionResult", "best_five",
    "category_name", "combination_counts", "count_board_runouts",
    "count_complete_deals", "evaluate", "evaluate_five", "full_deck",
    "iter_complete_deals", "parse_cards", "possible_board_runouts",
    "possible_hole_cards", "possible_next_boards", "possible_opponent_hands",
    "sample_deals", "showdown", "unseen_cards",
]
