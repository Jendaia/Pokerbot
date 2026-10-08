from __future__ import annotations

from dataclasses import asdict, dataclass

from ..core.cards import parse_cards
from ..core.game_state import GameState


@dataclass(frozen=True, slots=True)
class ObservedCard:
    """A client card; unknown/special values retain their raw identity."""

    id: int
    suit: str
    rank: str
    code: str | None


@dataclass(frozen=True, slots=True)
class ObservedPlayer:
    id: int
    name: str | None
    seat: int
    stack: float
    bet: float
    folded: bool
    sitting_out: bool
    playing: bool
    cards_count: int
    is_hero: bool = False
    has_timer: bool | None = None


@dataclass(frozen=True, slots=True)
class TableObservation:
    """One best-effort, consistency-checked snapshot of the client's table."""

    captured_at: str
    pid: int
    table_id: int
    game_id: int
    game_type: str
    view: str
    spectating: bool
    spectators: int
    seats: tuple[int, ...]
    dealer_seat: int | None
    acting_seat: int | None
    players: tuple[ObservedPlayer, ...]
    board: tuple[ObservedCard, ...]
    hero_id: int | None
    hero_cards: tuple[ObservedCard, ...]
    collected_pot: int
    street_bets_total: float
    small_blind: int
    game_in_progress: bool
    result_in_progress: bool

    @property
    def acting_player_id(self) -> int | None:
        return next((player.id for player in self.players if player.seat == self.acting_seat), None)

    @property
    def street(self) -> str:
        return {0: "pre-flop", 3: "flop", 4: "turn", 5: "river"}.get(len(self.board), "transition")

    @property
    def stage(self) -> str:
        if self.result_in_progress:
            return "showdown"
        return self.street if self.game_in_progress else "between-hands"

    @property
    def pot_total(self) -> float:
        return self.collected_pot + self.street_bets_total

    def to_game_state(self) -> GameState:
        """Use only known hero/board cards; opponents are uniform unknowns."""
        if self.spectating:
            raise ValueError("Spectators have no personal hand to calculate equity for")
        if self.game_type != "Texas":
            raise ValueError(f"The calculator requires Texas Hold'em, not {self.game_type}")
        if not self.game_in_progress or self.result_in_progress:
            raise ValueError("Equity requires a hand in progress before the result animation")
        hero = next((player for player in self.players if player.id == self.hero_id and player.is_hero), None)
        if hero is None or hero.folded or hero.sitting_out or not hero.playing:
            raise ValueError("The local player is not active in this hand")
        if len(self.hero_cards) != 2 or any(card.code is None for card in (*self.hero_cards, *self.board)):
            raise ValueError("Two resolved hero cards and a resolved board are required")
        opponents = sum(player.id != self.hero_id and player.playing and not player.folded
                        and player.cards_count > 0 for player in self.players)
        if not opponents:
            raise ValueError("There are no active opponents to evaluate")
        return GameState(
            hero=parse_cards(" ".join(card.code for card in self.hero_cards)),
            board=parse_cards(" ".join(card.code for card in self.board)),
            opponents=opponents,
        )

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result.update({
            "schema_version": 1,
            "source": "pokerist-il2cpp-linux",
            "stage": self.stage,
            "street": self.street,
            "player_count": len(self.players),
            "acting_player_id": self.acting_player_id,
            "pot_total": self.pot_total,
            "pot_formula": "TableMoney + sum(players.TableAmount)",
        })
        return result
