from itertools import combinations
import random
import unittest

from texasholdem.core.cards import full_deck, parse_cards
from texasholdem.core.hand_evaluator import best_five, category_name, evaluate, evaluate_five
from reference import reference_five


class HandEvaluatorTests(unittest.TestCase):
    def test_each_category(self):
        cases = {
            "As Ks Qs Js Ts 2d 3c": "Straight Flush",
            "Ah Ad Ac As 2d 3c 4h": "Four of a Kind",
            "Kh Kd Ks 2c 2h 8d 9c": "Full House",
            "Ah Jh 8h 4h 2h Kd Qs": "Flush",
            "9c 8d 7s 6h 5c Ad 2d": "Straight",
            "Qh Qd Qs 9c 4d 3s 2h": "Three of a Kind",
            "Jh Jd 8s 8c Ah 3d 2c": "Two Pair",
            "Th Td As 9c 7h 4d 2c": "One Pair",
            "As Jd 9c 7h 4s 3d 2c": "High Card",
        }
        for cards, expected in cases.items():
            with self.subTest(expected):
                self.assertEqual(category_name(evaluate(parse_cards(cards))), expected)

    def test_wheel_is_five_high(self):
        wheel = evaluate(parse_cards("As 2d 3h 4c 5s 9d Tc"))
        six_high = evaluate(parse_cards("2s 3d 4h 5c 6s 9d Tc"))
        self.assertGreater(six_high, wheel)

    def test_kickers_break_pair_ties(self):
        ace_kicker = evaluate(parse_cards("Ks Kd Ah Qc 8s 3d 2c"))
        queen_kicker = evaluate(parse_cards("Ks Kd Qh Jc 8s 3d 2c"))
        self.assertGreater(ace_kicker, queen_kicker)

    def test_two_trips_make_highest_full_house(self):
        self.assertEqual(evaluate(parse_cards("Ah Ad Ac Kh Kd Kc 2s")), (6, 14, 13))

    def test_three_pairs_use_top_two_and_best_remaining_kicker(self):
        self.assertEqual(evaluate(parse_cards("Ah Ad Kh Kd Qh Qd Js")), (2, 14, 13, 12))

    def test_seven_card_flush_uses_top_five(self):
        self.assertEqual(evaluate(parse_cards("Ah Kh Jh 8h 7h 4h 2h")), (5, 14, 13, 11, 8, 7))

    def test_board_can_be_best_hand(self):
        cards = parse_cards("2c 3d As Ks Qs Js Ts")
        self.assertEqual(set(best_five(cards)), set(cards[2:]))

    def test_duplicate_and_invalid_lengths_rejected(self):
        for cards in ("As As 2c 3d 4h", "As Ah", "As Ah Ks Kh Qs Qh Js Jh"):
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                evaluate(parse_cards(cards))
        with self.assertRaises(ValueError):
            evaluate_five(parse_cards("As Kh Qd Jc Ts 2h"))

    def test_direct_evaluator_matches_independent_five_card_oracle(self):
        rng = random.Random(451)
        deck = full_deck()
        for size in (5, 6, 7):
            for _ in range(500):
                cards = tuple(rng.sample(deck, size))
                expected = max(reference_five(hand) for hand in combinations(cards, 5))
                self.assertEqual(evaluate(cards), expected, tuple(map(str, cards)))


if __name__ == "__main__":
    unittest.main()
