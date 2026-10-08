from dataclasses import replace
import unittest

from texasholdem.dashboard.analysis import analyze_state, round_metrics, scenario_state
from native.test_observation import observation


class DashboardAnalysisTests(unittest.TestCase):
    def test_exact_showdown_and_all_hand_categories(self):
        state, samples = scenario_state({"hero": "As Ks", "board": "Qs Js Ts 2d 3c", "opponents": 1})
        result = analyze_state(state, simulations=samples)
        self.assertEqual(result["equity"]["win_percentage"], 100)
        self.assertEqual(result["equity"]["equity_percentage"], 100)
        self.assertTrue(result["equity"]["is_exact"])
        self.assertEqual(result["current_hand"]["category"], "Straight Flush")
        self.assertEqual(result["distribution"]["hand_categories"]["Straight Flush"], 100)
        self.assertEqual(len(result["distribution"]["hand_categories"]), 9)
        self.assertEqual(result["combinations"]["complete_deals"], 990)

    def test_board_only_royal_flush_has_tie_and_shared_pot_equity(self):
        state, _ = scenario_state({"hero": "2c 3d", "board": "As Ks Qs Js Ts", "opponents": 1})
        result = analyze_state(state)
        self.assertEqual(result["equity"]["tie_percentage"], 100)
        self.assertEqual(result["equity"]["win_percentage"], 0)
        self.assertEqual(result["equity"]["equity_percentage"], 50)

    def test_preflop_reports_estimate_and_confidence_bound(self):
        state, _ = scenario_state({"hero": "As Ah", "opponents": 2})
        result = analyze_state(state, simulations=1000, seed=42)
        self.assertFalse(result["equity"]["is_exact"])
        self.assertEqual(result["equity"]["trials"], 1000)
        self.assertEqual(result["current_hand"]["category"], "Pocket pair")
        self.assertEqual(len(result["equity"]["equity_95_interval"]), 2)
        self.assertAlmostEqual(sum(result["distribution"]["hand_categories"].values()), 100)

    def test_invalid_or_unbounded_scenario_requests_rejected(self):
        for payload in ([], {"hero": "As As"}, {"hero": "As Ah", "board": "As 3c 4d"},
                        {"hero": "As Ah", "board": "3c 4d"}, {"hero": "As Ah", "opponents": True},
                        {"hero": "As Ah", "opponents": 10}, {"hero": "As Ah", "simulations": 50001},
                        {"hero": ["As", "Ah"]}, {"hero": "As Ah", "simulations": 999}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                scenario_state(payload)

    def test_round_metrics_and_spectator_dont_fabricate_call(self):
        sample = observation()
        result = round_metrics(sample)
        self.assertEqual(result["active_players"], 2)
        self.assertEqual(result["to_call"], 75)
        self.assertAlmostEqual(result["call_pot_odds_percentage"], 100 * 75 / 450)
        self.assertIsNone(round_metrics(replace(sample, spectating=True))["to_call"])
        self.assertIsNone(round_metrics(replace(sample, result_in_progress=True))["to_call"])

    def test_call_is_capped_by_remaining_stack(self):
        sample = observation()
        sample = replace(sample, players=(replace(sample.players[0], stack=10), *sample.players[1:]))
        self.assertEqual(round_metrics(sample)["to_call"], 10)

    def test_large_combination_counts_preserved_as_exact_decimal_strings(self):
        from math import comb, prod
        state, _ = scenario_state({"hero": "As Ah", "opponents": 9})
        result = analyze_state(state, simulations=1000, seed=42)
        expected = comb(50, 5) * prod(comb(45 - 2 * index, 2) for index in range(9))
        self.assertGreater(expected, 2 ** 53)
        self.assertEqual(result["exact_counts"]["complete_deals"], str(expected))
