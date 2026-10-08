"""Alternating, vector-form CFR+ over an abstract heads-up river betting tree.

Every legal private combination has separate regrets; no hand buckets, sampled
showdowns, or knowledge of the opponent's actual hand. The betting menu is an
abstraction and the input ranges are estimates. This is not safe continual
resolving and its subgame gap is NOT exploitability of the full poker policy.
Algorithm: Tammelin (2014), https://arxiv.org/abs/1407.5042.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

import numpy as np

from ..pots import pot_payout


@dataclass(slots=True)
class Node:
    state: object
    actions: tuple
    children: tuple
    regret: object
    average: object


class RiverSolver:
    def __init__(self, state, space, ranges, root_actions, *, cap, max_raises=2):
        if state.board_len != 5 or len(state.live) != 2 or state.terminal:
            raise ValueError("River CFR requires exactly two live players on the river")
        self.space, self.initial = space, state
        self.players = (state.actor, next(i for i in state.live if i != state.actor))
        self.ranges = tuple(np.asarray(row, dtype=float) for row in ranges)
        n = len(space.hands)
        if len(self.ranges) != 2 or any(row.shape != (n,) or not np.isfinite(row).all() or (row < 0).any() or row.sum() <= 0 for row in self.ranges):
            raise ValueError("Two finite nonnegative board-legal ranges are required")
        self.ranges = tuple(row / row.sum() for row in self.ranges)
        self.joint_mass = float(np.dot(self.ranges[0], space.compatible_mass(self.ranges[1])))
        if self.joint_mass <= 0:
            raise ValueError("The two ranges have no compatible deal")
        self.nodes = 0
        self.iterations = 0
        self._payoffs = {}

        def build(s, root=False):
            if s.terminal:
                return s
            # Two raises AFTER this decision, irrespective of the prior line.
            actions = root_actions if root else s.actions(cap=cap if s.actor == state.actor else float("inf"),
                                                          max_raises=state.raises + max_raises)
            self.nodes += 1
            if self.nodes > 512:
                raise ValueError("River betting tree exceeds the node budget")
            shape = (len(actions), n)
            return Node(s, actions, tuple(build(s.apply(a)) for a in actions), np.zeros(shape), np.zeros(shape))

        self.root = build(state, True)

    @staticmethod
    def strategy(values):
        total = values.sum(axis=0)
        return np.divide(values, total, out=np.full_like(values, 1 / len(values)), where=total > 0)

    def terminal_values(self, state, player, other_reach):
        key = (state.committed, state.folded, player)
        if key not in self._payoffs:
            seat = self.players[player]
            amounts = dict(zip(state.ids, state.committed))
            cost = state.committed[seat] - self.initial.committed[seat]
            payoffs = []
            for ours, theirs in ((2, 1), (1, 1), (1, 2)):
                ranks = {state.ids[i]: (ours if i == seat else theirs,) for i in state.live}
                payoffs.append(pot_payout(amounts, ranks, state.ids[seat]) - cost)
            self._payoffs[key] = tuple(payoffs)
        payoffs = self._payoffs[key]
        if len(state.live) == 1:
            return payoffs[0] * self.space.compatible_mass(other_reach)
        return sum(value * mass for value, mass in zip(payoffs, self.space.outcome_mass(other_reach)))

    def _walk(self, node, player, own, other, *, update=False, best_response=False):
        if not isinstance(node, Node):
            return self.terminal_values(node, player, other)
        sigma = self.strategy(node.regret if update else node.average)
        ours = node.state.actor == self.players[player]
        if ours:
            values = np.array([self._walk(child, player, own * sigma[i], other,
                                         update=update, best_response=best_response)
                               for i, child in enumerate(node.children)])
            if best_response:
                return values.max(axis=0)
            expected = np.sum(sigma * values, axis=0)
            if update:
                np.maximum(0, node.regret + values - expected, out=node.regret)
                node.average += self.iterations * own * sigma
            return expected
        return sum(self._walk(child, player, own, other * sigma[i], update=update,
                              best_response=best_response) for i, child in enumerate(node.children))

    def solve(self, iterations=1000, *, deadline=float("inf"), cancelled=lambda: False):
        for _ in range(iterations):
            if cancelled():
                raise ValueError("Decision was cancelled")
            if time.monotonic() >= deadline:
                break
            self.iterations += 1
            for player in (0, 1):
                self._walk(self.root, player, self.ranges[player], self.ranges[1 - player], update=True)
        if cancelled():
            raise ValueError("Decision was cancelled")
        return self

    def distribution(self, hand):
        index = self.space.index[tuple(sorted(hand))]
        return self.strategy(self.root.average)[:, index]

    def action_values(self, hand):
        index = self.space.index[tuple(sorted(hand))]
        mass = self.space.compatible_mass(self.ranges[1])[index]
        return np.array([self._walk(child, 0, self.ranges[0], self.ranges[1])[index] / mass
                         for child in self.root.children])

    def gap(self):
        """Exact sum of unilateral improvements for THIS tree and THESE ranges."""
        values, responses = [], []
        for player in (0, 1):
            own, other = self.ranges[player], self.ranges[1 - player]
            values.append(float(np.dot(own, self._walk(self.root, player, own, other))) / self.joint_mass)
            responses.append(float(np.dot(own, self._walk(self.root, player, own, other, best_response=True))) / self.joint_mass)
        return {"nash_conv_chips": max(0., sum(responses) - sum(values)),
                "profile_values": values, "best_response_values": responses}
