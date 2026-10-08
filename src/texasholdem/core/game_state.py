from __future__ import annotations

from dataclasses import dataclass

from .cards import Card, ensure_unique


@dataclass(frozen=True, slots=True)
class GameState:
    """Known information at any Hold'em street."""

    hero: tuple[Card, Card]
    board: tuple[Card, ...] = ()
    opponents: int = 1
    opponent_hands: tuple[tuple[Card, ...], ...] = ()
    dead_cards: tuple[Card, ...] = ()

    def __post_init__(self) -> None:
        # Copy input sequences so a caller cannot mutate a validated state.
        object.__setattr__(self, "hero", tuple(self.hero))
        object.__setattr__(self, "board", tuple(self.board))
        object.__setattr__(self, "dead_cards", tuple(self.dead_cards))
        if len(self.hero) != 2:
            raise ValueError("Hero must have exactly two hole cards")
        if len(self.board) not in (0, 3, 4, 5):
            raise ValueError("Board must contain 0 (pre-flop), 3 (flop), 4 (turn), or 5 (river) cards")
        if type(self.opponents) is not int or not 1 <= self.opponents <= 9:
            raise ValueError("Opponent count must be between 1 and 9")
        hands = tuple(tuple(hand) for hand in self.opponent_hands)
        if len(hands) > self.opponents:
            raise ValueError("More opponent hands supplied than opponent seats")
        if any(len(hand) > 2 for hand in hands):
            raise ValueError("An opponent hand must contain zero, one, or two known cards")
        hands += ((),) * (self.opponents - len(hands))
        object.__setattr__(self, "opponent_hands", hands)
        ensure_unique(self.known_cards)
        needed = self.missing_board_cards + sum(self.unknown_cards_per_opponent)
        if needed > 52 - len(self.known_cards):
            raise ValueError("Not enough unseen cards to complete the board and opponent hands")

    @property
    def street(self) -> str:
        return {0: "pre-flop", 3: "flop", 4: "turn", 5: "river"}[len(self.board)]

    @property
    def missing_board_cards(self) -> int:
        return 5 - len(self.board)

    @property
    def known_cards(self) -> tuple[Card, ...]:
        return self.hero + self.board + self.dead_cards + tuple(
            card for hand in self.opponent_hands for card in hand
        )

    @property
    def unknown_cards_per_opponent(self) -> tuple[int, ...]:
        return tuple(2 - len(hand) for hand in self.opponent_hands)

    def as_dict(self) -> dict[str, object]:
        return {
            "street": self.street,
            "hero": [str(card) for card in self.hero],
            "board": [str(card) for card in self.board],
            "opponents": self.opponents,
            "opponent_hands": [[str(card) for card in hand] for hand in self.opponent_hands],
            "dead_cards": [str(card) for card in self.dead_cards],
        }
