from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite

from ..models.observation import TableObservation


@dataclass(frozen=True, slots=True)
class BotSettings:
    samples: int = 3000
    think_seconds: float = 2.0
    max_action_chips: int | None = None
    stop_loss_chips: int | None = None
    max_hands: int | None = None
    strategy: str = "hybrid"
    objective: str = "profit"

    @classmethod
    def from_dict(cls, data: dict) -> "BotSettings":
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise ValueError("Unknown bot setting")
        settings = cls(**data)
        if settings.strategy not in ("hybrid", "search", "rollout"):
            raise ValueError("strategy must be hybrid, search, or rollout")
        if settings.objective not in ("profit", "balanced", "conservative"):
            raise ValueError("objective must be profit, balanced, or conservative")
        for name, lower, upper in (("samples", 200, 20000), ("max_action_chips", 1, 10**9),
                                   ("stop_loss_chips", 1, 10**9), ("max_hands", 1, 10000)):
            value = getattr(settings, name)
            if name != "samples" and value is None:
                continue
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer between {lower} and {upper}")
        if type(settings.think_seconds) not in (int, float) or not isfinite(settings.think_seconds) or not .2 <= settings.think_seconds <= 5:
            raise ValueError("think_seconds must be between 0.2 and 5")
        return settings

    @property
    def action_cap(self) -> float:
        """No user cap still respects the stack and the client's legal bounds."""
        return float("inf") if self.max_action_chips is None else self.max_action_chips

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Action:
    kind: str
    # Raise amounts are additional chips taken from the current stack,
    # matching Pokerist's native UIRaiseBet.Value (not a total street wager).
    amount: int = 0

    def __post_init__(self):
        if self.kind not in ("fold", "check", "call", "raise"):
            raise ValueError("Choose fold, check, call, or raise")
        if type(self.amount) is not int or self.amount < 0 or (self.kind != "raise" and self.amount):
            raise ValueError("Only a raise accepts a positive integer chip amount")
        if self.kind == "raise" and self.amount == 0:
            raise ValueError("A raise requires a positive chip amount")

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    reason: str
    equity: float
    pot_odds: float
    samples: int
    elapsed_seconds: float
    candidates: tuple[dict, ...]
    method: str = "rollout-v1"
    diagnostics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def turn_key(observation: TableObservation, hand_number: int) -> tuple:
    """All public inputs which can change the legality or cost of an action."""
    return (observation.pid, observation.table_id, hand_number, observation.hero_id,
            observation.acting_player_id, observation.dealer_seat,
            tuple(c.code for c in observation.hero_cards), tuple(c.code for c in observation.board),
            observation.collected_pot, observation.game_in_progress, observation.result_in_progress,
            observation.spectating, tuple(sorted((p.id, p.seat, p.stack, p.bet, p.folded,
                                                  p.sitting_out, p.playing, p.cards_count)
                                                 for p in observation.players)))
