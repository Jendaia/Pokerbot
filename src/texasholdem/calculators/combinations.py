from __future__ import annotations

from itertools import combinations
from math import comb
from typing import Iterator

from ..core.cards import Card, ensure_unique, full_deck
from ..core.game_state import GameState
from ..models.deals import Deal


def unseen_cards(state: GameState) -> tuple[Card, ...]:
    known = set(state.known_cards)
    return tuple(card for card in full_deck() if card not in known)


def count_board_runouts(state: GameState) -> int:
    return comb(52 - len(state.known_cards), state.missing_board_cards)


def possible_board_runouts(state: GameState) -> Iterator[tuple[Card, ...]]:
    """Yield every unordered set of future board cards; river yields one empty set."""
    yield from combinations(unseen_cards(state), state.missing_board_cards)


def possible_next_boards(state: GameState) -> Iterator[tuple[Card, ...]]:
    """Yield boards at the next street (flops pre-flop, then turns or rivers)."""
    if not state.missing_board_cards:
        return
    next_count = 3 if not state.board else 1
    for additions in combinations(unseen_cards(state), next_count):
        yield state.board + additions


def possible_hole_cards(available: tuple[Card, ...]) -> Iterator[tuple[Card, Card]]:
    """Yield every two-card holding from supplied distinct available cards."""
    ensure_unique(available)
    yield from combinations(available, 2)


def possible_opponent_hands(state: GameState, seat: int = 0) -> Iterator[tuple[Card, ...]]:
    """Yield legal holdings for one zero-based opponent seat at the current street."""
    if type(seat) is not int or not 0 <= seat < state.opponents:
        raise ValueError("Opponent seat is out of range")
    for additions in combinations(unseen_cards(state), state.unknown_cards_per_opponent[seat]):
        yield tuple(sorted(state.opponent_hands[seat] + additions))


def count_complete_deals(state: GameState) -> int:
    """Exact allocation count: unordered runout and unordered cards within each seat.

    Seats are distinguished. Burning cards and the order of future community
    cards are marginalized because neither changes a showdown outcome.
    """
    available = 52 - len(state.known_cards)
    count = comb(available, state.missing_board_cards)
    available -= state.missing_board_cards
    for needed in state.unknown_cards_per_opponent:
        count *= comb(available, needed)
        available -= needed
    return count


def combination_counts(state: GameState) -> dict[str, object]:
    runouts = count_board_runouts(state)
    total = count_complete_deals(state)
    return {
        "unseen_cards": 52 - len(state.known_cards),
        "board_runouts": runouts,
        "opponent_holdings_at_current_street": [
            comb(52 - len(state.known_cards), needed)
            for needed in state.unknown_cards_per_opponent
        ],
        "opponent_allocations_per_runout": total // runouts,
        "complete_deals": total,
    }


def _opponent_allocations(
    state: GameState,
    available: tuple[Card, ...],
    seat: int = 0,
    hands: tuple[tuple[Card, ...], ...] = (),
) -> Iterator[tuple[tuple[Card, ...], ...]]:
    if seat == state.opponents:
        yield hands
        return
    for additions in combinations(available, state.unknown_cards_per_opponent[seat]):
        hand = tuple(sorted(state.opponent_hands[seat] + additions))
        if seat + 1 == state.opponents:
            yield hands + (hand,)
            continue
        used = set(additions)
        remaining = tuple(card for card in available if card not in used)
        yield from _opponent_allocations(state, remaining, seat + 1, hands + (hand,))


def iter_complete_deals(state: GameState) -> Iterator[Deal]:
    """Stream all complete legal deals without materializing the search space."""
    unseen = unseen_cards(state)
    for runout in combinations(unseen, state.missing_board_cards):
        used = set(runout)
        available = tuple(card for card in unseen if card not in used)
        for hands in _opponent_allocations(state, available):
            yield Deal(state.board + runout, hands)
