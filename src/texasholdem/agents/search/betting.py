from __future__ import annotations

from dataclasses import dataclass, replace

from ..models import Action
from ..sizing import native_actions  # Public compatibility import for existing integrations.


@dataclass(frozen=True, slots=True)
class BettingState:
    """Chip-conserving no-limit continuation, in clockwise seat order.

    Contributions include folded money. A short all-in increases the price but
    does not reopen raising for a player who already acted. Cards live outside
    this public state, so a policy cannot inspect another player's holding.
    """
    ids: tuple[int, ...]
    stacks: tuple[float, ...]
    bets: tuple[float, ...]
    committed: tuple[float, ...]
    folded: tuple[bool, ...]
    pending: frozenset[int]
    raise_rights: frozenset[int]
    actor: int
    button: int
    board_len: int
    min_raise: float
    big_blind: float
    raises: int = 0
    terminal: bool = False

    @classmethod
    def from_frame(cls, frame, tracker):
        o = frame.observation
        players = sorted(o.players, key=lambda p: p.seat)
        hero = next(i for i, p in enumerate(players) if p.id == o.hero_id)
        folded = tuple(p.folded or not p.playing or not p.cards_count for p in players)
        active = {i for i, p in enumerate(players) if not folded[i] and p.stack > 0}
        acted = set()
        raises = 0
        for event in tracker.public_actions:
            if event.street != o.street:
                continue
            if event.action == "raise":
                # The native hero raise flag is authoritative at the root;
                # subsequent short raises are handled exactly by apply().
                acted.clear()
                raises += 1
            acted.add(event.player_id)
        highest = max(p.bet for p in players)
        if o.board and highest > 0:
            # A player who has already made/matched this street's high bet
            # cannot get a second turn after our closing call. This remains
            # observable when polling missed the action itself.
            acted.update(p.id for p in players if p.bet == highest)
        pending = {i for i in active if players[i].id not in acted or players[i].bet < highest}
        pending.add(hero)
        rights = {i for i in active if players[i].id not in acted}
        if "raise" in frame.legal:
            rights.add(hero)
        contributions = tracker.contributions(o)
        # The button may be an empty seat; the previous occupied seat gives
        # the same clockwise first actor on the next street.
        before = [i for i, p in enumerate(players) if p.seat <= (o.dealer_seat or 0)]
        button = before[-1] if before else len(players) - 1
        return cls(tuple(p.id for p in players), tuple(p.stack for p in players),
                   tuple(p.bet for p in players), tuple(contributions.get(p.id, 0) for p in players),
                   folded, frozenset(pending), frozenset(rights), hero, button, len(o.board),
                   max(o.small_blind * 2, tracker.last_raise), o.small_blind * 2, raises)

    @property
    def pot(self):
        return sum(self.committed)

    @property
    def live(self):
        return tuple(i for i, folded in enumerate(self.folded) if not folded)

    @property
    def call(self):
        return min(self.stacks[self.actor], max(self.bets) - self.bets[self.actor])

    def actions(self, *, cap=float("inf"), max_raises=2):
        if self.terminal:
            return ()
        result = [Action("fold" if self.call else "check")]
        if 0 < self.call <= cap:
            result.append(Action("call"))
        p = self.actor
        if p in self.raise_rights and self.raises < max_raises and any(self.stacks[i] > 0 for i in self.live if i != p):
            maximum = int(min(self.stacks[p], cap))
            minimum = int(max(self.bets) - self.bets[p] + self.min_raise)
            sizes = {minimum, int(self.stacks[p])}
            for fraction in (.5, 1.):
                sizes.add(max(minimum, round(self.call + fraction * (self.pot + self.call))))
            for amount in sorted(sizes):
                if self.call < amount <= maximum and (amount >= minimum or amount == self.stacks[p]):
                    result.append(Action("raise", amount))
        return tuple(result)

    def apply(self, action):
        if self.terminal:
            raise ValueError("Cannot act in a finished hand")
        p = self.actor
        stacks, bets, committed, folded = list(self.stacks), list(self.bets), list(self.committed), list(self.folded)
        pending, rights = set(self.pending) - {p}, set(self.raise_rights) - {p}
        minimum, raises = self.min_raise, self.raises
        if action.kind == "fold":
            if not self.call:
                raise ValueError("Use check when nothing is owed")
            folded[p] = True
            cost = 0
        elif action.kind == "check":
            if self.call:
                raise ValueError("Cannot check facing a bet")
            cost = 0
        elif action.kind == "call":
            if not self.call:
                raise ValueError("Nothing to call")
            cost = self.call
        else:
            cost = action.amount
            increment = bets[p] + cost - max(bets)
            if p not in self.raise_rights or not self.call < cost <= stacks[p] or (increment < minimum and cost != stacks[p]):
                raise ValueError("Illegal raise in continuation")
            others = {i for i in self.live if i != p and stacks[i] > 0}
            if not others:
                raise ValueError("No opponent can answer a raise")
            pending |= others
            if increment >= minimum:
                rights = others
                minimum = increment
            raises += 1
        stacks[p] -= cost
        bets[p] += cost
        committed[p] += cost
        pending = {i for i in pending if not folded[i] and stacks[i] > 0}
        result = replace(self, stacks=tuple(stacks), bets=tuple(bets), committed=tuple(committed),
                         folded=tuple(folded), pending=frozenset(pending), raise_rights=frozenset(rights),
                         min_raise=minimum, raises=raises)
        if len(result.live) == 1:
            return replace(result, terminal=True)
        if not pending:
            active = {i for i in result.live if stacks[i] > 0}
            if self.board_len == 5 or len(active) < 2:
                return replace(result, board_len=5, terminal=True)
            board_len = {0: 3, 3: 4, 4: 5}[self.board_len]
            first = next((self.button + offset) % len(stacks) for offset in range(1, len(stacks) + 1)
                         if (self.button + offset) % len(stacks) in active)
            return replace(result, bets=(0.,) * len(stacks), pending=frozenset(active),
                           raise_rights=frozenset(active), actor=first, board_len=board_len,
                           min_raise=self.big_blind, raises=0)
        following = next((p + offset) % len(stacks) for offset in range(1, len(stacks) + 1)
                         if (p + offset) % len(stacks) in pending)
        return replace(result, actor=following)
