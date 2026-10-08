from __future__ import annotations

from dataclasses import dataclass

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_NAMES = {
    "2": "Two", "3": "Three", "4": "Four", "5": "Five", "6": "Six",
    "7": "Seven", "8": "Eight", "9": "Nine", "T": "Ten", "J": "Jack",
    "Q": "Queen", "K": "King", "A": "Ace",
}
SUIT_NAMES = {"c": "clubs", "d": "diamonds", "h": "hearts", "s": "spades"}


@dataclass(frozen=True, order=True, slots=True)
class Card:
    """A standard playing card, written rank first: As, Td, 2c."""

    rank: int
    suit: str

    def __post_init__(self) -> None:
        if (
            type(self.rank) is not int
            or not 2 <= self.rank <= 14
            or not isinstance(self.suit, str)
            or self.suit not in tuple(SUITS)
        ):
            raise ValueError(f"Invalid card: rank={self.rank}, suit={self.suit!r}")

    @classmethod
    def parse(cls, text: str) -> "Card":
        value = text.strip()
        if value[:2] == "10":
            value = "T" + value[2:]
        if len(value) != 2:
            raise ValueError(f"Invalid card {text!r}; use notation such as As, Td, or 2c")
        rank_text, suit = value[0].upper(), value[1].lower()
        if rank_text not in RANKS or suit not in SUITS:
            raise ValueError(f"Invalid card {text!r}; ranks are 2-A and suits are c/d/h/s")
        return cls(RANKS.index(rank_text) + 2, suit)

    def __str__(self) -> str:
        return f"{RANKS[self.rank - 2]}{self.suit}"

    @property
    def name(self) -> str:
        return f"{RANK_NAMES[RANKS[self.rank - 2]]} of {SUIT_NAMES[self.suit]}"


def full_deck() -> tuple[Card, ...]:
    return tuple(Card(rank, suit) for rank in range(2, 15) for suit in SUITS)


def parse_cards(text: str) -> tuple[Card, ...]:
    """Parse whitespace/comma separated cards, e.g. ``As Kh`` or ``As,Kh``."""
    return tuple(Card.parse(item) for item in text.replace(",", " ").split())


def ensure_unique(cards: tuple[Card, ...] | list[Card]) -> None:
    if any(not isinstance(card, Card) for card in cards):
        raise ValueError("Cards must be Card objects; use parse_cards to convert text")
    if len(set(cards)) != len(cards):
        duplicates = sorted({str(card) for card in cards if cards.count(card) > 1})
        raise ValueError(f"Duplicate card(s): {', '.join(duplicates)}")
