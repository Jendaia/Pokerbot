from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import random

import numpy as np

from ...core.cards import Card, full_deck
from ...core.hand_evaluator import _evaluate_unchecked
from ..opponents import OpponentProfile, sigmoid
from ..policy import preflop_strength


def draw_potential(hand, board):
    """A likelihood feature, not an equity claim. Includes wheel/flush draws."""
    if len(board) not in (3, 4):
        return 0.
    cards = (*hand, *board)
    suits = [c.suit for c in cards]
    flush = any(suits.count(suit) == 4 and any(c.suit == suit for c in hand) for suit in set(suits))
    ranks = {c.rank for c in cards}
    if 14 in ranks:
        ranks.add(1)
    outs = {r for low in range(1, 11) if len(set(range(low, low + 5)) - ranks) == 1
            for r in set(range(low, low + 5)) - ranks}
    # A draw on the board belongs to everybody; do not credit it twice.
    board_ranks = {c.rank for c in board}
    if 14 in board_ranks:
        board_ranks.add(1)
    straight = bool(outs) and any(c.rank not in board_ranks for c in hand)
    return min(.45, (.28 if flush else 0) + (.23 if straight and len(outs) > 1 else .12 if straight else 0))


class RangeSpace:
    """Every board-legal combination; the hero's actual hand is not removed.

    Solvers need a public range for BOTH players. Conditioning on the actual
    hero cards here would tell the simulated opponent those private cards.
    Blockers are applied in terminal values or joint deal sampling instead.
    """
    def __init__(self, board):
        self.board = tuple(board)
        deck = tuple(c for c in full_deck() if c not in board)
        self.hands = tuple(combinations(deck, 2))
        self.index = {hand: i for i, hand in enumerate(self.hands)}
        self.card_ids = np.array([[(c.rank - 2) * 4 + "cdhs".index(c.suit) for c in hand]
                                  for hand in self.hands], dtype=np.int32)
        self.masks = tuple((1 << int(a)) | (1 << int(b)) for a, b in self.card_ids)
        if board:
            ranks = [_evaluate_unchecked((*hand, *board)) for hand in self.hands]
            unique = {rank: i for i, rank in enumerate(sorted(set(ranks)))}
            self.groups = np.array([unique[r] for r in ranks], dtype=np.int32)
            self.group_count = len(unique)
            counts = np.bincount(self.groups)
            percentile = (np.cumsum(counts) - counts * .5)[self.groups] / len(self.hands)
            draws = np.array([draw_potential(hand, board) for hand in self.hands])
            self.strengths = np.minimum(.995, percentile + (1 - percentile) * draws)
        else:
            self.groups = np.zeros(len(self.hands), dtype=np.int32)
            self.group_count = 1
            self.strengths = np.array([preflop_strength(hand) for hand in self.hands])

    def compatible_mass(self, weights):
        card = np.bincount(self.card_ids.ravel(), weights=np.repeat(weights, 2), minlength=52)
        return np.maximum(0., weights.sum() - card[self.card_ids[:, 0]] - card[self.card_ids[:, 1]] + weights)

    def outcome_mass(self, weights):
        """Exact less/equal/greater rank mass with two-card removal, O(52R+N)."""
        n = self.group_count
        group = np.bincount(self.groups, weights=weights, minlength=n)
        cg = (self.card_ids * n + self.groups[:, None]).ravel()
        card = np.bincount(cg, weights=np.repeat(weights, 2), minlength=52 * n).reshape(52, n)
        prefix = np.cumsum(group) - group
        cp = np.cumsum(card, axis=1) - card
        a, b = self.card_ids.T
        win = np.maximum(0., prefix[self.groups] - cp[a, self.groups] - cp[b, self.groups])
        tie = np.maximum(0., group[self.groups] - card[a, self.groups] - card[b, self.groups] + weights)
        lose = np.maximum(0., self.compatible_mass(weights) - win - tie)
        return win, tie, lose

    def weights(self, tracker, player_id):
        weights = np.ones(len(self.hands))
        profile = tracker.profiles.get(player_id, OpponentProfile())
        # Evidence is evaluated on the board where the action occurred. A
        # river improvement must not retrospectively explain a flop raise.
        for event in tracker.public_actions:
            if event.player_id != player_id or event.action == "fold":
                continue
            earlier = range_space(tuple(Card.parse(c) for c in event.board))
            strength = np.array([earlier.strengths[earlier.index[hand]] for hand in self.hands])
            price = event.facing / max(1., event.pot + event.facing)
            threshold = .42 + .38 * price - .12 * (profile.looseness - .5)
            if not event.board:
                threshold += .10 * (1 - event.position)
            continuation = .08 + .9 / (1 + np.exp(-9 * (strength - threshold)))
            aggression = .035 + .8 / (1 + np.exp(-13 * (strength - threshold - .22)))
            if event.action == "raise":
                likelihood = aggression
            elif event.action == "call":
                likelihood = continuation * (1 - aggression)
            else:
                likelihood = 1 - aggression
            # Modest confidence in a heuristic action model. This floor also
            # keeps plausible bluffs/draws alive under sparse observations.
            weights *= .2 + .8 * likelihood
        weights /= weights.sum()
        return .8 * weights + .2 / len(weights)


@lru_cache(maxsize=12)
def range_space(board: tuple[Card, ...]) -> RangeSpace:
    return RangeSpace(board)


class JointSampler:
    """Independent range product conditioned on disjoint cards by rejection.

    Reject the WHOLE deal, not just the next seat; sequential rejection biases
    earlier seats. A failed draw is skipped instead of inventing uniform hands.
    """
    def __init__(self, space, ranges, known):
        self.space = space
        self.known = set(known)
        self.rows = []
        for weights in ranges:
            row = np.array(weights, copy=True)
            row[[i for i, hand in enumerate(space.hands) if self.known.intersection(hand)]] = 0
            if row.sum() <= 0:
                raise ValueError("No compatible hands in opponent range")
            self.rows.append(np.cumsum(row / row.sum()))

    def sample(self, rng: random.Random, cancelled=lambda: False):
        for attempt in range(512):
            if attempt % 32 == 0 and cancelled():
                raise ValueError("Decision was cancelled")
            used, result = 0, []
            for row in self.rows:
                index = min(len(row) - 1, int(np.searchsorted(row, rng.random(), side="right")))
                mask = self.space.masks[index]
                if used & mask:
                    break
                used |= mask
                result.append(self.space.hands[index])
            else:
                return tuple(result)
        return None


def response_distribution(strength, price, opponents, profile=None):
    """Smoothed population model used ONLY for continuation rollouts."""
    profile = profile or OpponentProfile()
    equity = strength ** max(1, opponents * .72)
    continue_p = .03 + .94 * sigmoid(13 * (equity - price - .08 + .16 * (profile.looseness - .5)))
    value_raise = sigmoid(16 * (equity - .73)) * (.28 + .7 * profile.aggression)
    bluff = .025 * (1 - strength) * (1 + profile.aggression)
    raise_p = min(.85, value_raise + bluff)
    if price > 0:
        return (1 - continue_p, continue_p * (1 - raise_p), continue_p * raise_p)
    return (0., 1 - raise_p, raise_p)
