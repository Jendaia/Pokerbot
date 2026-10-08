from __future__ import annotations

from itertools import combinations
from typing import Sequence

from .cards import Card, ensure_unique

HAND_NAMES = (
    "High Card", "One Pair", "Two Pair", "Three of a Kind", "Straight",
    "Flush", "Full House", "Four of a Kind", "Straight Flush",
)

# Higher tuples win; category first, followed by all relevant kickers.
HandRank = tuple[int, ...]


def _straight_high(ranks: Sequence[int]) -> int:
    values = set(ranks)
    if 14 in values:
        values.add(1)
    for high in range(14, 4, -1):
        if all(rank in values for rank in range(high - 4, high + 1)):
            return high
    return 0


def _evaluate_unchecked(cards: Sequence[Card]) -> HandRank:
    """Fast evaluation for cards already validated by GameState."""
    counts: dict[int, int] = {}
    suits: dict[str, list[int]] = {}
    for card in cards:
        counts[card.rank] = counts.get(card.rank, 0) + 1
        suits.setdefault(card.suit, []).append(card.rank)
    ranks = sorted(counts, reverse=True)
    flush_ranks = next((sorted(rs, reverse=True) for rs in suits.values() if len(rs) >= 5), [])
    if flush_ranks:
        straight_flush = _straight_high(flush_ranks)
        if straight_flush:
            return (8, straight_flush)
    quads = [rank for rank in ranks if counts[rank] == 4]
    if quads:
        return (7, quads[0], next(rank for rank in ranks if rank != quads[0]))
    trips = [rank for rank in ranks if counts[rank] >= 3]
    if trips:
        full_house_pairs = [rank for rank in ranks if rank != trips[0] and counts[rank] >= 2]
        if full_house_pairs:
            return (6, trips[0], full_house_pairs[0])
    if flush_ranks:
        return (5, *flush_ranks[:5])
    straight = _straight_high(ranks)
    if straight:
        return (4, straight)
    if trips:
        return (3, trips[0], *[rank for rank in ranks if rank != trips[0]][:2])
    pairs = [rank for rank in ranks if counts[rank] == 2]
    if len(pairs) >= 2:
        return (2, *pairs[:2], next(rank for rank in ranks if rank not in pairs[:2]))
    if pairs:
        return (1, pairs[0], *[rank for rank in ranks if rank != pairs[0]][:3])
    return (0, *ranks[:5])


def evaluate_five(cards: Sequence[Card]) -> HandRank:
    """Rank exactly five distinct cards; a royal flush is an ace-high straight flush."""
    if len(cards) != 5:
        raise ValueError("evaluate_five requires exactly five cards")
    ensure_unique(tuple(cards))
    return _evaluate_unchecked(cards)


def evaluate(cards: Sequence[Card]) -> HandRank:
    """Rank the best five-card hand from five, six, or seven distinct cards.

    Direct rank/suit counting avoids evaluating all 21 five-card subsets in
    every simulated seven-card hand. Hole cards need not be used.
    """
    if not 5 <= len(cards) <= 7:
        raise ValueError("A poker hand evaluation requires five to seven cards")
    ensure_unique(tuple(cards))
    return _evaluate_unchecked(cards)


def best_five(cards: Sequence[Card]) -> tuple[Card, ...]:
    """Return one best five-card subset (equivalent suit choices can tie)."""
    evaluate(cards)  # Validate once before enumerating subsets.
    return max(combinations(cards, 5), key=_evaluate_unchecked)


def category_name(rank: HandRank) -> str:
    return HAND_NAMES[rank[0]]
