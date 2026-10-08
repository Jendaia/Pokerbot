from collections import Counter
from fractions import Fraction
from itertools import combinations, permutations
from math import comb
import unittest

from texasholdem import (
    Deal, EquityCalculator, GameState, combination_counts, count_board_runouts,
    count_complete_deals, iter_complete_deals, parse_cards, possible_board_runouts,
    possible_next_boards, possible_opponent_hands, sample_deals, unseen_cards,
)
from helpers import small_state
from reference import reference_five


class CombinationTests(unittest.TestCase):
    def test_counts_at_every_street(self):
        for board in ("", "2c 3d 4h", "2c 3d 4h 5s", "2c 3d 4h 5s 6c"):
            state = GameState(parse_cards("As Kh"), parse_cards(board))
            expected = comb(50 - len(state.board), 5 - len(state.board))
            self.assertEqual(count_board_runouts(state), expected)
            self.assertEqual(count_complete_deals(state), expected * 990)
        state = GameState(parse_cards("As Kh"), parse_cards("2c 3d 4h 5s 6c"), 2)
        self.assertEqual(count_complete_deals(state), comb(45, 2) * comb(43, 2))

    def test_allocation_enumeration_matches_independent_permutations(self):
        state = small_state()
        expected = set()
        for dealt in permutations(unseen_cards(state), 4):
            expected.add(Deal(
                state.board + (dealt[0],),
                (tuple(sorted(state.opponent_hands[0] + (dealt[1],))), tuple(sorted(dealt[2:]))),
            ))
        actual = list(iter_complete_deals(state))
        self.assertEqual(len(expected), 180)
        self.assertEqual(len(actual), 180)
        self.assertEqual(set(actual), expected)
        self.assertEqual(count_complete_deals(state), len(actual))
        self.assertEqual(combination_counts(state)["opponent_allocations_per_runout"], 30)

    def test_exhaustive_equity_matches_independent_showdown_oracle(self):
        state = small_state()
        counts = Counter()
        shares = Fraction(0)
        for deal in iter_complete_deals(state):
            hands = (state.hero, *deal.opponent_hands)
            ranks = [max(reference_five(five) for five in combinations(hand + deal.board, 5)) for hand in hands]
            best = max(ranks)
            winners = [index for index, rank in enumerate(ranks) if rank == best]
            if 0 not in winners:
                counts["losses"] += 1
            elif len(winners) == 1:
                counts["wins"] += 1
                shares += 1
            else:
                counts["ties"] += 1
                shares += Fraction(1, len(winners))
        actual = EquityCalculator().calculate(state, mode="exact")
        self.assertEqual((actual.wins, actual.ties, actual.losses),
                         (counts["wins"], counts["ties"], counts["losses"]))
        self.assertAlmostEqual(actual.equity_share, float(shares))
        sampled = EquityCalculator().calculate(state, mode="monte-carlo", simulations=4_000, seed=4)
        self.assertAlmostEqual(sampled.equity_percentage / 100, actual.equity_percentage / 100, delta=0.04)

    def test_samples_respect_known_cards_and_have_no_collisions(self):
        state = small_state()
        dead = set(state.dead_cards)
        for deal in sample_deals(state, 200, seed=5):
            cards = state.hero + deal.board + tuple(card for hand in deal.opponent_hands for card in hand)
            self.assertEqual(len(cards), len(set(cards)))
            self.assertFalse(dead.intersection(cards))
            self.assertIn(state.opponent_hands[0][0], deal.opponent_hands[0])
        nine = GameState(parse_cards("As Ah"), opponents=9)
        for deal in sample_deals(nine, 10, seed=6):
            cards = nine.hero + deal.board + tuple(card for hand in deal.opponent_hands for card in hand)
            self.assertEqual(len(cards), 25)
            self.assertEqual(len(cards), len(set(cards)))

    def test_sample_allocations_are_approximately_uniform(self):
        state = small_state()
        counts = Counter(sample_deals(state, 18_000, seed=92))
        self.assertEqual(len(counts), 180)
        self.assertGreater(min(counts.values()), 60)
        self.assertLess(max(counts.values()), 140)

    def test_partial_and_known_opponent_holdings(self):
        state = GameState(parse_cards("As Kh"), parse_cards("2c 3d 4h 8s 9c"), 2,
                          (parse_cards("Qc Qd"), parse_cards("Js")))
        self.assertEqual(list(possible_opponent_hands(state)), [parse_cards("Qc Qd")])
        self.assertEqual(len(list(possible_opponent_hands(state, 1))), 42)
        with self.assertRaises(ValueError):
            list(possible_opponent_hands(state, 2))

    def test_next_streets_and_river_runout(self):
        for board, additions in (("", 3), ("2c 3d 4h", 1), ("2c 3d 4h 5s", 1)):
            state = GameState(parse_cards("As Kh"), parse_cards(board))
            next_boards = list(possible_next_boards(state))
            self.assertEqual(len(next_boards), comb(50 - len(state.board), additions))
            self.assertEqual(len(next_boards[0]), len(state.board) + additions)
        river = GameState(parse_cards("As Kh"), parse_cards("2c 3d 4h 5s 6c"))
        self.assertEqual(list(possible_board_runouts(river)), [()])
        self.assertEqual(list(possible_next_boards(river)), [])
