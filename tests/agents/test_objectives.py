from dataclasses import replace
import json
import unittest

from texasholdem.agents.models import Action, BotSettings
from texasholdem.agents.objectives import score, utility
from texasholdem.agents.policy import RolloutPolicy
from texasholdem.agents.sizing import native_actions
from texasholdem.agents.strategy import HybridPolicy
from agents.test_search import valid_frame


class ObjectiveTests(unittest.TestCase):
    def test_unlimited_defaults_round_trip_and_optional_caps_validate(self):
        settings = BotSettings.from_dict({})
        self.assertEqual(settings.objective, "profit")
        self.assertEqual(settings.action_cap, float("inf"))
        self.assertIsNone(settings.max_hands)
        self.assertIsNone(settings.stop_loss_chips)
        self.assertEqual(BotSettings.from_dict(json.loads(json.dumps(settings.as_dict(), allow_nan=False))), settings)
        limited = BotSettings.from_dict({"max_action_chips": 123, "stop_loss_chips": None, "max_hands": 5})
        self.assertEqual(limited.action_cap, 123)
        for key in ("max_action_chips", "stop_loss_chips", "max_hands"):
            for invalid in (0, -1, True, 1.5, "unlimited", float("inf")):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    BotSettings.from_dict({key: invalid})
        for invalid in ({"samples": None}, {"objective": "money"}, {"objective": None}):
            with self.assertRaises(ValueError):
                BotSettings.from_dict(invalid)

    def test_risk_objective_can_prefer_a_smaller_return_and_scales_with_stack(self):
        safe, risky = [20, 20], [150, -100]
        expected = lambda outcomes, stack, goal: sum(utility(v, stack, goal) for v in outcomes) / len(outcomes)
        self.assertGreater(expected(risky, 100, "profit"), expected(safe, 100, "profit"))
        self.assertLess(expected(risky, 100, "conservative"), expected(safe, 100, "conservative"))
        self.assertGreater(expected(risky, 1000, "conservative"), expected(safe, 1000, "conservative"))
        self.assertEqual(utility(-1000, 1000, "conservative"), 10 * utility(-100, 100, "conservative"))
        self.assertEqual(score(25, 10, "profit"), 25)
        self.assertLess(score(25, 10, "conservative"), score(20, 0, "conservative"))

    def test_menu_scales_with_table_stakes_and_all_in_is_available_without_cap(self):
        frame, tracker = valid_frame(facing=False)
        frame = replace(frame, raise_steps=tuple(range(50, 1001, 50)))
        menu = native_actions(frame, tracker, BotSettings())
        self.assertIn(Action("raise", 1000), menu)
        self.assertIn(Action("raise", 300), menu)  # 1.5-pot overbet.
        o = frame.observation
        scale = 100
        large = replace(frame, observation=replace(o, small_blind=o.small_blind * scale,
                        collected_pot=o.collected_pot * scale, street_bets_total=o.street_bets_total * scale,
                        players=tuple(replace(p, stack=p.stack * scale, bet=p.bet * scale) for p in o.players)),
                        raise_min=frame.raise_min * scale, raise_max=frame.raise_max * scale,
                        raise_steps=tuple(v * scale for v in frame.raise_steps))
        large_menu = native_actions(large, tracker, BotSettings())
        self.assertEqual(large_menu, tuple(Action(a.kind, a.amount * scale) for a in menu))
        self.assertTrue(all(a.kind != "raise" or a.amount <= 5000
                            for a in native_actions(large, tracker, BotSettings(max_action_chips=5000))))
        self.assertIn(Action("raise", 100_000), large_menu)

    def test_large_calls_follow_optional_cap_and_incomplete_ledgers_do_not_bet(self):
        f, t = valid_frame()
        players = tuple(replace(p, stack=p.stack * 100, bet=p.bet * 100) for p in f.observation.players)
        f = replace(f, observation=replace(f.observation, players=players))
        self.assertIn(Action("call"), native_actions(f, t, BotSettings()))
        self.assertNotIn(Action("call"), native_actions(f, t, BotSettings(max_action_chips=1000)))
        t.ledger_complete = False
        self.assertEqual(native_actions(f, t, BotSettings()), (Action("fold"),))

    def test_profit_river_chooses_max_ev_and_does_not_claim_mixed_profile_gap(self):
        f, t = valid_frame()
        d = HybridPolicy().decide(f, t, BotSettings(samples=200, think_seconds=1, max_action_chips=100), seed=7)
        self.assertEqual(d.method, "river-cfr+-ev")
        self.assertEqual(d.action.kind, "call")
        best = max(d.candidates, key=lambda c: c["ev_chips"])
        self.assertEqual(d.action.kind, best["action"])
        self.assertNotIn("nash_conv_chips", d.diagnostics)
        self.assertIn("solver_nash_conv_chips", d.diagnostics)
        self.assertEqual(best["probability"], 1.)
        self.assertIn("solver_probability", best)

    def test_objective_applies_to_real_rollout_and_conservative_river_routing(self):
        f, t = valid_frame(hero="As Ah", board="Ks 7c 4d 2h 9s")
        profit = RolloutPolicy().decide(f, t, BotSettings(samples=200, think_seconds=2), seed=4)
        self.assertEqual(max(c["score"] for c in profit.candidates), max(c["ev_chips"] for c in profit.candidates))
        conservative = HybridPolicy().decide(f, t, BotSettings(samples=200, think_seconds=2, objective="conservative"), seed=4)
        self.assertEqual(conservative.method, "rollout-v1")
        self.assertEqual(conservative.diagnostics["objective"], "conservative")
        self.assertTrue(any(c["utility_chips"] < c["ev_chips"] for c in conservative.candidates))
        self.assertTrue(all(c["score"] <= c["utility_chips"] for c in conservative.candidates))
