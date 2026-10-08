from __future__ import annotations

from dataclasses import dataclass, field
from math import exp

from ..models.observation import TableObservation


def sigmoid(value: float) -> float:
    return 1 / (1 + exp(-max(-30, min(30, value))))


@dataclass(slots=True)
class OpponentProfile:
    actions: int = 0
    folds: int = 0
    calls: int = 0
    raises: int = 0
    checks: int = 0

    @property
    def looseness(self) -> float:
        return (self.calls + self.raises + 4) / (self.calls + self.raises + self.folds + 8)

    @property
    def aggression(self) -> float:
        return (self.raises + 2) / (self.calls + self.raises + 6)

    def as_dict(self) -> dict:
        return {"actions": self.actions, "folds": self.folds, "calls": self.calls, "raises": self.raises,
                "checks": self.checks, "looseness": self.looseness, "aggression": self.aggression}


@dataclass(frozen=True, slots=True)
class PublicAction:
    player_id: int
    action: str
    street: str
    board: tuple[str, ...]
    amount: float
    facing: float
    pot: float
    position: float


@dataclass(slots=True)
class HandTracker:
    """Infer public actions and track committed chips across betting streets.

    Actions are not inferred across missing hands. At a street transition,
    only the previous actor's observable closing call/check/fold is recorded.
    Attaching after bets have entered the collected pot is deliberately marked
    incomplete: the policy can check/fold until a new preflop is observed.
    """
    previous: TableObservation | None = None
    hand_number: int | None = None
    profiles: dict[int, OpponentProfile] = field(default_factory=dict)
    evidence: dict[int, list[tuple[str, str, float]]] = field(default_factory=dict)
    committed: dict[int, float] = field(default_factory=dict)
    ledger_complete: bool = False
    hands: int = 0
    last_raise: float = 0
    public_actions: list[PublicAction] = field(default_factory=list)

    def observe(self, observation: TableObservation, hand_number: int) -> None:
        old = self.previous
        new = old is None or old.table_id != observation.table_id or self.hand_number != hand_number
        if old and observation.game_in_progress and observation.street == "pre-flop" and old.street != "pre-flop":
            new = True
        if old and observation.game_in_progress and not observation.result_in_progress and observation.street == "pre-flop" and (old.result_in_progress or not old.game_in_progress):
            new = True
        if new:
            self.evidence = {}
            self.public_actions = []
            self.committed = {p.id: 0. for p in observation.players}
            self.ledger_complete = observation.game_in_progress and observation.collected_pot == 0
            self.last_raise = observation.small_blind * 2
            self.hands += 1
        elif observation.game_in_progress and not observation.result_in_progress:
            before = {p.id: p for p in old.players}
            if old.street != observation.street:
                after = {p.id: p for p in observation.players}
                for p in old.players:
                    current = after.get(p.id)
                    final_call = max(0, p.stack - current.stack - current.bet) if current else 0
                    self.committed[p.id] = self.committed.get(p.id, 0) + p.bet + final_call
                    if current and old.acting_player_id == p.id:
                        if current.folded and not p.folded:
                            self._record(old, p, "fold", 0)
                        elif final_call > 0:
                            self._record(old, p, "call", final_call)
                        elif p.stack > 0 and not p.folded and p.bet == max(q.bet for q in old.players):
                            self._record(old, p, "check", 0)
                self.last_raise = observation.small_blind * 2
            else:
                max_before = max((p.bet for p in old.players), default=0)
                for p in observation.players:
                    prev = before.get(p.id)
                    if prev is None or not (p.playing or prev.playing):
                        continue
                    action = None
                    if p.folded and not prev.folded:
                        action = "fold"
                    elif p.bet > prev.bet:
                        if old.acting_player_id != p.id:
                            continue  # Automatic blinds are not voluntary actions.
                        action = "raise" if p.bet > max_before else "call"
                        if action == "raise":
                            self.last_raise = max(self.last_raise, p.bet - max_before)
                    elif old.acting_player_id == p.id and observation.acting_player_id != p.id and not p.folded and p.stack > 0 and prev.bet == max_before:
                        action = "check"
                    if action:
                        self._record(old, prev, action, max(0, p.bet - prev.bet))
            total = sum(self.committed.values())
            if abs(total - observation.collected_pot) > .01:
                # Uncalled-bet returns or a missed street make the ledger uncertain.
                self.ledger_complete = False
        self.previous, self.hand_number = observation, hand_number

    def _record(self, observation, player, action, amount):
        active = sorted((p for p in observation.players if p.playing and not p.folded), key=lambda p: p.seat)
        after_button = sorted(active, key=lambda p: (p.seat - (observation.dealer_seat or 0) - 1) % 10)
        position = next((i for i, p in enumerate(after_button) if p.id == player.id), 0) / max(1, len(active) - 1)
        facing = max(0, max(p.bet for p in observation.players) - player.bet)
        self.public_actions.append(PublicAction(player.id, action, observation.street,
                                  tuple(c.code for c in observation.board if c.code), amount,
                                  facing, observation.pot_total, position))
        # Hero history conditions the hero's public range too. Personal cards
        # are never an input to an opponent's simulated strategy.
        price = amount / max(1, observation.pot_total + amount)
        if action in ("raise", "call"):
            self.evidence.setdefault(player.id, []).append((action, observation.street, price))
        if player.id != observation.hero_id:
            profile = self.profiles.setdefault(player.id, OpponentProfile())
            profile.actions += 1
            attr = {"fold": "folds", "raise": "raises", "call": "calls", "check": "checks"}[action]
            setattr(profile, attr, getattr(profile, attr) + 1)

    def contributions(self, observation: TableObservation) -> dict[int, float]:
        result = dict(self.committed)
        for p in observation.players:
            result[p.id] = result.get(p.id, 0) + p.bet
        return result

    def range_weight(self, id_: int, strength: float, street: str) -> float:
        profile = self.profiles.get(id_, OpponentProfile())
        weight = 1.
        # Older-street evidence uses a softer likelihood; a made-hand percentile
        # can change sharply on a new board. All hypotheses retain nonzero mass.
        for action, observed_street, price in self.evidence.get(id_, ())[-5:]:
            softness = .65 if observed_street != street else 1.
            threshold = (.57 if action == "raise" else .35) + price * .35 - (profile.looseness - .5) * .2
            likelihood = .08 + .92 * sigmoid((strength - threshold) * (8 if action == "raise" else 5))
            weight *= likelihood ** softness
        return max(1e-5, weight)

    def call_probability(self, id_: int, strength: float, price: float, street: str) -> float:
        profile = self.profiles.get(id_, OpponentProfile())
        threshold = .30 + price * .65 + (.06 if street == "river" else 0) - (profile.looseness - .5) * .25
        return .03 + .94 * sigmoid((strength - threshold) * 9)
