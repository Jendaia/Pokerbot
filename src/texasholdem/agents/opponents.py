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


@dataclass(slots=True)
class HandTracker:
    """Infer public actions and track committed chips across betting streets.

    We never infer an action across missing hands or a street transition.
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

    def observe(self, observation: TableObservation, hand_number: int) -> None:
        old = self.previous
        new = old is None or old.table_id != observation.table_id or self.hand_number != hand_number
        if old and observation.game_in_progress and observation.street == "pre-flop" and old.street != "pre-flop":
            new = True
        if old and observation.game_in_progress and not observation.result_in_progress and observation.street == "pre-flop" and (old.result_in_progress or not old.game_in_progress):
            new = True
        if new:
            self.evidence = {}
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
            else:
                max_before = max((p.bet for p in old.players), default=0)
                for p in observation.players:
                    prev = before.get(p.id)
                    if prev is None or p.id == observation.hero_id or not p.playing:
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
                    elif old.acting_player_id == p.id and observation.acting_player_id != p.id and not p.folded and p.stack > 0:
                        action = "check"
                    if action:
                        profile = self.profiles.setdefault(p.id, OpponentProfile())
                        profile.actions += 1
                        attr = {"fold": "folds", "raise": "raises", "call": "calls", "check": "checks"}[action]
                        setattr(profile, attr, getattr(profile, attr) + 1)
                        price = max(0, p.bet - prev.bet) / max(1, old.pot_total + max(0, p.bet - prev.bet))
                        if action in ("raise", "call"):
                            self.evidence.setdefault(p.id, []).append((action, observation.street, price))
            total = sum(self.committed.values())
            if abs(total - observation.collected_pot) > .01:
                # Uncalled-bet returns or a missed street make the ledger uncertain.
                self.ledger_complete = False
        self.previous, self.hand_number = observation, hand_number

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
