from __future__ import annotations

from dataclasses import dataclass

from ..core.cards import Card


@dataclass(frozen=True, slots=True)
class Deal:
    """One complete board and one holding per labelled opponent seat."""

    board: tuple[Card, ...]
    opponent_hands: tuple[tuple[Card, ...], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "board": [str(card) for card in self.board],
            "opponent_hands": [[str(card) for card in hand] for hand in self.opponent_hands],
        }
