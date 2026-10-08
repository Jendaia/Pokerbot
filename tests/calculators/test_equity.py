import unittest

from texasholdem import EquityCalculator, GameState, parse_cards
from texasholdem.calculators.combinations import count_complete_deals


class CalculatorTests(unittest.TestCase):
    def test_river_heads_up_deal_count(self):
        state = GameState(parse_cards("As Ah"), parse_cards("2c 3d 4h 8s Kc"), 1)
        self.assertEqual(count_complete_deals(state), 990)  # C(45, 2)

    def test_exact_locked_royal_flush_never_loses(self):
        state = GameState(parse_cards("As Ks"), parse_cards("Qs Js Ts 2d 3c"), 1)
        result = EquityCalculator().calculate(state, mode="exact")
        self.assertEqual(result.trials, 990)
        self.assertEqual(result.wins + result.ties, 990)
        self.assertEqual(result.losses, 0)

    def test_board_royal_flush_always_ties(self):
        state = GameState(parse_cards("2c 3d"), parse_cards("As Ks Qs Js Ts"), 1)
        result = EquityCalculator().calculate(state, mode="exact")
        self.assertEqual(result.ties, 990)
        self.assertAlmostEqual(result.equity_percentage, 50.0)

    def test_auto_uses_monte_carlo_preflop(self):
        state = GameState(parse_cards("As Ah"), opponents=1)
        result = EquityCalculator().calculate(state, simulations=100, seed=7)
        self.assertEqual(result.mode, "monte-carlo")
        self.assertEqual(result.trials, 100)
        self.assertEqual(result.wins + result.ties + result.losses, 100)

    def test_duplicate_cards_rejected(self):
        with self.assertRaises(ValueError):
            GameState(parse_cards("As Ah"), parse_cards("As 2d 3c"), 1)

    def test_known_opponents_can_split_three_ways(self):
        state = GameState(
            parse_cards("2c 3d"), parse_cards("As Ks Qs Js Ts"), opponents=2,
            opponent_hands=(parse_cards("4c 5d"), parse_cards("6c 7d")),
        )
        result = EquityCalculator().calculate(state, mode="exact")
        self.assertEqual(result.total_possible, 1)
        self.assertEqual(result.ties, 1)
        self.assertAlmostEqual(result.equity_percentage, 100 / 3)
        self.assertEqual(result.equity_95_interval, (result.equity_percentage,) * 2)

    def test_hero_ties_one_opponent_and_beats_another(self):
        state = GameState(
            parse_cards("As Kd"), parse_cards("Ah 2c 3d 7h 8s"), opponents=2,
            opponent_hands=(parse_cards("Ac Ks"), parse_cards("Qd Qc")),
        )
        result = EquityCalculator().calculate(state)
        self.assertEqual(result.ties, 1)
        self.assertEqual(result.equity_percentage, 50)

    def test_an_opponent_can_beat_hero_and_another_tied_hand(self):
        state = GameState(
            parse_cards("As Kd"), parse_cards("Ah 2c 3d 7h 8s"), opponents=2,
            opponent_hands=(parse_cards("Ac Ks"), parse_cards("7d 7c")),
        )
        result = EquityCalculator().calculate(state)
        self.assertEqual(result.losses, 1)
        self.assertEqual(result.equity_percentage, 0)

    def test_all_streets_and_seeded_sampling(self):
        for board in ("", "Ks Qh 2d", "Ks Qh 2d 8c", "Ks Qh 2d 8c 9s"):
            state = GameState(parse_cards("As Ah"), parse_cards(board), 3)
            first = EquityCalculator().calculate(state, mode="monte-carlo", simulations=100, seed=19)
            second = EquityCalculator().calculate(state, mode="monte-carlo", simulations=100, seed=19)
            self.assertEqual(first.as_dict(), second.as_dict())
            self.assertEqual(first.wins + first.ties + first.losses, 100)
            self.assertAlmostEqual(sum(first.category_percentages().values()), 100)
            self.assertLessEqual(first.win_percentage, first.equity_percentage)
            self.assertLessEqual(first.equity_percentage, first.win_percentage + first.tie_percentage)

    def test_large_exact_calculation_requires_explicit_override(self):
        state = GameState(parse_cards("As Ah"))
        with self.assertRaisesRegex(ValueError, "allow_large_exact"):
            EquityCalculator().calculate(state, mode="exact")
        river = GameState(parse_cards("As Ks"), parse_cards("Qs Js Ts 2d 3c"))
        result = EquityCalculator(max_exact_trials=1).calculate(river, mode="exact", allow_large_exact=True)
        self.assertEqual(result.trials, 990)

    def test_bad_calculation_settings_rejected(self):
        state = GameState(parse_cards("As Ah"))
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EquityCalculator().calculate(state, simulations=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                EquityCalculator(max_exact_trials=value)
        with self.assertRaises(ValueError):
            EquityCalculator().calculate(state, mode="typo")

    def test_sampled_uncertainty_is_not_zero_after_all_wins(self):
        state = GameState(parse_cards("As Ks"), parse_cards("Qs Js Ts 2d 3c"))
        result = EquityCalculator().calculate(state, mode="monte-carlo", simulations=100, seed=1)
        self.assertEqual(result.win_percentage, 100)
        low, high = result.equity_95_interval
        self.assertLess(low, 100)
        self.assertEqual(high, 100)
        self.assertEqual(result.equity_standard_error_percentage, 0)

    def test_single_sample_has_no_sample_standard_error(self):
        state = GameState(parse_cards("As Ah"))
        result = EquityCalculator().calculate(state, mode="monte-carlo", simulations=1, seed=1)
        self.assertIsNone(result.equity_standard_error_percentage)


if __name__ == "__main__":
    unittest.main()
