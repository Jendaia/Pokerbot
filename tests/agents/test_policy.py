from dataclasses import replace
import unittest

from texasholdem.agents.models import Action, BotSettings
from texasholdem.agents.opponents import HandTracker
from texasholdem.agents.policy import RolloutPolicy, preflop_strength
from texasholdem.agents.pots import pot_payout
from texasholdem.analyzers.native.controls import ControlButton, ControlFrame
from texasholdem.core.cards import parse_cards
from native.test_observation import observation, cards


def frame(**changes):
    obs = replace(observation(), acting_seat=1, collected_pot=0, **changes)
    buttons = tuple(ControlButton(kind, kind, True, (10., 10., 20., 20.)) for kind in ("fold", "call", "raise"))
    return ControlFrame(obs, 1, True, buttons, (100., 100.), True, 175, 1000, 175)


class PolicyTests(unittest.TestCase):
    def test_royal_flush_calls_profitably_and_respects_action_cap(self):
        f = frame()
        tracker = HandTracker()
        tracker.observe(f.observation, 1)
        settings = BotSettings(samples=200, max_action_chips=100, think_seconds=1)
        decision = RolloutPolicy().decide(f, tracker, settings, seed=7)
        self.assertEqual(decision.action.kind, "call")
        self.assertEqual(decision.equity, 1)
        self.assertEqual(decision.samples, 200)
        self.assertFalse(any(c["action"] == "raise" for c in decision.candidates))

    def test_free_check_is_preferred_to_folding_a_board_tie(self):
        f = frame(board=cards("As Ks Qs Js Ts"), hero_cards=cards("2c 3d"))
        f = replace(f, buttons=(ControlButton("check", "Check", True, (0, 0, 10, 10)), ControlButton("fold", "Fold", True, (0, 0, 10, 10))))
        tracker = HandTracker(); tracker.observe(f.observation, 1)
        result = RolloutPolicy().decide(f, tracker, BotSettings(samples=200, think_seconds=1), seed=9)
        self.assertEqual(result.action.kind, "check")
        self.assertEqual(result.equity, .5)

    def test_incomplete_ledger_never_spends_chips(self):
        f = frame()
        tracker = HandTracker()
        tracker.observe(replace(f.observation, collected_pot=200), 1)
        decision = RolloutPolicy().decide(f, tracker, BotSettings(samples=200, think_seconds=1), seed=1)
        self.assertEqual(decision.action.kind, "fold")
        self.assertIn("ledger", decision.reason)

    def test_no_opponent_turn_or_illegal_raise(self):
        f = replace(frame(), observation=observation())
        tracker = HandTracker()
        with self.assertRaises(ValueError):
            RolloutPolicy().decide(f, tracker, BotSettings(samples=200))
        with self.assertRaises(ValueError):
            Action("raise", 0)
        with self.assertRaises(ValueError):
            Action("call", 50)

    def test_preflop_prior_orders_obvious_hands(self):
        self.assertGreater(preflop_strength(parse_cards("As Ah")), preflop_strength(parse_cards("7c 2d")))
        self.assertGreater(preflop_strength(parse_cards("As Ks")), preflop_strength(parse_cards("Ac Kd")))

    def test_main_side_pots_and_uncalled_chips(self):
        contributions = {1: 100, 2: 300, 3: 300, 4: 50}
        ranks = {1: (8, 14), 2: (2, 12, 9), 3: (1, 14)}
        self.assertEqual(pot_payout(contributions, ranks, 1), 350)
        self.assertEqual(pot_payout(contributions, ranks, 2), 400)
        self.assertEqual(pot_payout({1: 500, 2: 100}, {1: (0, 2), 2: (8, 14)}, 1), 400)
        self.assertEqual(pot_payout({1: 100, 2: 100}, {1: (8, 14), 2: (8, 14)}, 1), 100)
        self.assertEqual(pot_payout({1: 300, 2: 100}, {2: (1, 14)}, 1), 200)

    def test_tracker_accounts_for_final_call_during_street_transition(self):
        f = frame(board=(), hero_cards=cards("As Kh"))
        tracker = HandTracker(); tracker.observe(f.observation, 1)
        players = tuple(replace(p, stack=p.stack - 75, bet=0) if p.is_hero else replace(p, bet=0) for p in f.observation.players)
        next_street = replace(f.observation, board=cards("2c 3d 9h"), players=players, collected_pot=250, street_bets_total=0)
        tracker.observe(next_street, 1)
        self.assertTrue(tracker.ledger_complete)
        self.assertEqual(tracker.contributions(next_street)[101], 100)

    def test_settings_reject_nan_booleans_and_unbounded_values(self):
        for data in ({"think_seconds": float("nan")}, {"samples": True}, {"max_action_chips": 0}, {"max_hands": 10001}, {"path": "x"}):
            with self.assertRaises(ValueError):
                BotSettings.from_dict(data)
