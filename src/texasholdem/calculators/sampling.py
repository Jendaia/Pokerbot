from __future__ import annotations

import random
from typing import Iterator

from ..core.game_state import GameState
from ..models.deals import Deal
from .combinations import unseen_cards


def sample_deals(state: GameState, simulations: int, seed: int | None = None) -> Iterator[Deal]:
    """Sample complete legal allocations uniformly, independently, without replacement within a deal."""
    if type(simulations) is not int or simulations < 1:
        raise ValueError("simulations must be a positive integer")
    rng = random.Random(seed)
    unseen = unseen_cards(state)
    needed = state.missing_board_cards + sum(state.unknown_cards_per_opponent)
    for _ in range(simulations):
        dealt = rng.sample(unseen, needed)
        offset = state.missing_board_cards
        board = state.board + tuple(sorted(dealt[:offset]))
        hands = []
        for known, count in zip(state.opponent_hands, state.unknown_cards_per_opponent):
            hands.append(tuple(sorted(known + tuple(dealt[offset:offset + count]))))
            offset += count
        yield Deal(board, tuple(hands))
