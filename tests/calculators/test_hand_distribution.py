import unittest

from texasholdem import GameState, HandDistributionCalculator, parse_cards


class HandDistributionTests(unittest.TestCase):
    def test_flush_draw_exact_count_with_card_exclusions(self):
        for dead, opponent, unseen, flushes in (("", "", 46, 9), ("Jh", "", 45, 8), ("", "Jh Jd", 44, 8)):
            state = GameState(
                parse_cards("Ah Kh"), parse_cards("Qh 2h 9c 7d"),
                opponent_hands=(parse_cards(opponent),), dead_cards=parse_cards(dead),
            )
            result = HandDistributionCalculator().calculate(state, mode="exact")
            self.assertEqual(result.trials, unseen)
            self.assertEqual(result.hand_categories["Flush"], flushes)
            self.assertAlmostEqual(result.category_percentages()["Flush"], 100 * flushes / unseen)
            self.assertAlmostEqual(sum(result.category_percentages().values()), 100)

    def test_flop_uses_all_board_runouts_without_opponent_enumeration(self):
        state = GameState(parse_cards("As Ah"), parse_cards("Ks 7d 2c"), opponents=9)
        result = HandDistributionCalculator().calculate(state)
        self.assertEqual(result.mode, "exact")
        self.assertEqual(result.trials, 1081)

    def test_river_has_one_final_hand(self):
        state = GameState(parse_cards("2c 3d"), parse_cards("As Ks Qs Js Ts"))
        result = HandDistributionCalculator().calculate(state)
        self.assertEqual(result.trials, 1)
        self.assertEqual(result.category_percentages()["Straight Flush"], 100)

    def test_seeded_preflop_distribution(self):
        state = GameState(parse_cards("As Ah"))
        calc = HandDistributionCalculator()
        first = calc.calculate(state, simulations=200, seed=14)
        second = calc.calculate(state, simulations=200, seed=14)
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(first.mode, "monte-carlo")
        self.assertEqual(first.total_possible, 2_118_760)
