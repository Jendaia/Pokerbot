from __future__ import annotations

from typing import Sequence

from .cards import Card, ensure_unique
from .hand_evaluator import HandRank, _evaluate_unchecked


def winning_seats(ranks: Sequence[HandRank]) -> tuple[int, ...]:
    """Return all winning seat indices; seat zero is the hero."""
    if not ranks:
        raise ValueError("At least one player is required")
    best = max(ranks)
    return tuple(index for index, rank in enumerate(ranks) if rank == best)


def showdown(hands: Sequence[Sequence[Card]], board: Sequence[Card]) -> tuple[int, ...]:
    """Resolve a completed Hold'em showdown, including ties and board-only hands."""
    if len(board) != 5 or not hands or any(len(hand) != 2 for hand in hands):
        raise ValueError("Showdown requires five board cards and two cards per player")
    ensure_unique(tuple(board) + tuple(card for hand in hands for card in hand))
    return winning_seats(tuple(_evaluate_unchecked((*hand, *board)) for hand in hands))
