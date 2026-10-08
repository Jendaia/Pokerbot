from dataclasses import replace
import random
import time
import unittest

import numpy as np

from texasholdem.agents.models import Action, BotSettings
from texasholdem.agents.opponents import HandTracker, PublicAction
from texasholdem.agents.search.betting import BettingState, native_actions
from texasholdem.agents.search.ranges import JointSampler, range_space
from texasholdem.agents.search.river import RiverSolver
from texasholdem.agents.search.rollout import MultiStreetPolicy, hand_equity_proxy
from texasholdem.agents.strategy import HybridPolicy
from texasholdem.analyzers.native.controls import ControlButton
from texasholdem.core.cards import parse_cards
from texasholdem.core.hand_evaluator import _evaluate_unchecked
from agents.test_policy import frame
from native.test_observation import cards


def valid_frame(board="Qs Js Ts 2d 3c", hero="As Ks", *, facing=True):
    f = frame(board=cards(board), hero_cards=cards(hero))
    players = (replace(f.observation.players[0], bet=0, stack=1000),
               replace(f.observation.players[1], bet=100 if facing else 0, stack=900))
    o = replace(f.observation, players=players, street_bets_total=100 if facing else 0,
                collected_pot=200, dealer_seat=3)
    kinds = ("fold", "call", "raise") if facing else ("check", "raise")
    f = replace(f, observation=o, raise_min=200 if facing else 50, raise_max=1000,
                raise_steps=(50, 100, 200, 300, 500, 1000),
                buttons=tuple(ControlButton(k, k, True, (1, 1, 5, 5)) for k in kinds))
    t = HandTracker(previous=o, hand_number=1, committed={101: 100., 102: 100.}, ledger_complete=True, last_raise=100 if facing else 50)
    return f, t


class BettingTests(unittest.TestCase):
    def test_closing_call_has_no_phantom_second_turn(self):
        f, t = valid_frame()
        state = BettingState.from_frame(f, t)
        after = state.apply(Action("call"))
        self.assertTrue(after.terminal)
        self.assertEqual(after.committed, (200, 200))
        self.assertEqual(sum(after.stacks) + after.pot, sum(state.stacks) + state.pot)

    def test_check_check_advances_and_button_sets_order(self):
        f, t = valid_frame(board="2c 3d 7h", hero="As Ks", facing=False)
        state = BettingState.from_frame(f, t)
        self.assertEqual(state.apply(Action("check")).actor, 1)
        after = state.apply(Action("check")).apply(Action("check"))
        self.assertEqual(after.board_len, 4)
        self.assertEqual(after.actor, 0)
        self.assertEqual(after.raises, 0)

    def test_short_all_in_does_not_reopen_and_uncalled_money_is_retained(self):
        state = BettingState((1, 2, 3), (900, 150, 1000), (100, 0, 0), (100, 0, 0),
                             (False, False, False), frozenset({1, 2}), frozenset({1, 2}), 1, 2, 5, 100, 100)
        after = state.apply(Action("raise", 150))
        self.assertNotIn(0, after.raise_rights)
        self.assertIn(2, after.raise_rights)
        after = after.apply(Action("call"))
        self.assertEqual(after.actor, 0)
        self.assertFalse(any(a.kind == "raise" for a in after.actions()))
        with self.assertRaises(ValueError):
            after.apply(Action("raise", 200))
        end = after.apply(Action("call"))
        self.assertTrue(end.terminal)
        self.assertEqual(end.committed, (150, 150, 150))

    def test_random_legal_continuations_terminate_and_conserve_chips(self):
        rng = random.Random(92)
        for n in (2, 3, 6, 9):
            for _ in range(30):
                state = BettingState(tuple(range(n)), tuple(rng.randrange(10, 1000) for _ in range(n)),
                                     (0.,) * n, (0.,) * n, (False,) * n, frozenset(range(n)),
                                     frozenset(range(n)), 0, n - 1, 0, 20, 20)
                wealth = sum(state.stacks)
                for count in range(160):
                    if state.terminal:
                        break
                    state = state.apply(rng.choice(state.actions()))
                    self.assertEqual(sum(state.stacks) + state.pot, wealth)
                    self.assertTrue(all(v >= 0 for v in state.stacks))
                self.assertTrue(state.terminal)


class RangeTests(unittest.TestCase):
    def test_blocker_sweep_matches_independent_enumeration(self):
        space = range_space(parse_cards("Ks 7c 4d 2h 9s"))
        rng = np.random.default_rng(42)
        weights = rng.random(len(space.hands)); weights /= weights.sum()
        win, tie, lose = space.outcome_mass(weights)
        for index in (0, 99, 777, 1080):
            hand = space.hands[index]
            rank = _evaluate_unchecked((*hand, *space.board))
            expected = [0., 0., 0.]
            for other, weight in zip(space.hands, weights):
                if set(hand).intersection(other):
                    continue
                theirs = _evaluate_unchecked((*other, *space.board))
                expected[0 if rank > theirs else 1 if rank == theirs else 2] += weight
            np.testing.assert_allclose([win[index], tie[index], lose[index]], expected, atol=1e-12)

    def test_history_uses_original_board_and_keeps_full_public_hero_range(self):
        f, t = valid_frame()
        t.public_actions.append(PublicAction(102, "raise", "pre-flop", (), 100, 50, 100, 0.))
        space = range_space(parse_cards("Qs Js Ts 2d 3c"))
        weights = space.weights(t, 102)
        aa = space.index[tuple(sorted(parse_cards("Ac Ah")))]
        trash = space.index[tuple(sorted(parse_cards("7c 4d")))]
        self.assertGreater(weights[aa], weights[trash])
        self.assertTrue(all(w > 0 for w in weights))
        self.assertTrue(any(set(parse_cards("As Ks")).intersection(hand) for hand in space.hands))

    def test_joint_sampling_has_no_collisions_and_is_seat_symmetric(self):
        space = range_space(parse_cards("Ks 7c 4d 2h 9s"))
        weights = np.zeros(len(space.hands))
        # Three equal options, one collision edge. Whole-deal rejection must
        # give the first and second seats the same marginal distribution.
        for text in ("As Ah", "As Qd", "Jc Tc"):
            weights[space.index[tuple(sorted(parse_cards(text)))]] = 1 / 3
        sampler = JointSampler(space, [weights, weights], ())
        rng = random.Random(72)
        counts = [0, 0]
        target = set(parse_cards("Jc Tc"))
        for _ in range(2000):
            deal = sampler.sample(rng)
            self.assertFalse(set(deal[0]).intersection(deal[1]))
            for i in (0, 1):
                counts[i] += set(deal[i]) == target
        self.assertLess(abs(counts[0] - counts[1]), 120)


class RiverTests(unittest.TestCase):
    def test_unequal_stacks_folded_money_and_uncalled_refunds(self):
        space = range_space(parse_cards("Ks 7c 4d 2h 9s"))
        state = BettingState((1, 2, 3), (50, 400, 0), (0, 0, 0), (100, 300, 100),
                             (False, False, True), frozenset({0, 1}), frozenset({0, 1}), 0, 2, 5, 20, 20)
        solver = RiverSolver(state, space, [np.ones(1081), np.ones(1081)], state.actions(), cap=1000)
        solver.solve(20)
        self.assertAlmostEqual(sum(solver.gap()["profile_values"]), 500, places=7)

    def test_nuts_call_and_exact_outcomes(self):
        f, t = valid_frame()
        d = HybridPolicy().decide(f, t, BotSettings(samples=200, think_seconds=1, max_action_chips=100, objective="balanced"), seed=7)
        self.assertEqual(d.method, "river-cfr+")
        self.assertEqual(d.action.kind, "call")
        self.assertEqual(d.equity, 1.)
        self.assertAlmostEqual(d.candidates[1]["ev_chips"], 300.)
        self.assertGreater(d.candidates[1]["probability"], .99)

    def test_cfr_gap_converges_and_utility_is_constant_sum(self):
        f, t = valid_frame(board="Ks 7c 4d 2h 9s", hero="As Ah", facing=False)
        state = BettingState.from_frame(f, t)
        space = range_space(parse_cards("Ks 7c 4d 2h 9s"))
        ours, theirs = np.zeros(len(space.hands)), np.zeros(len(space.hands))
        for hand in ("As Ah", "Qd Jh"):
            ours[space.index[tuple(sorted(parse_cards(hand)))]] = .5
        theirs[space.index[tuple(sorted(parse_cards("Kc Qh")))]] = 1
        solver = RiverSolver(state, space, [ours, theirs], (Action("check"), Action("raise", 200)), cap=1000, max_raises=1)
        initial = solver.gap()["nash_conv_chips"]
        solver.solve(350)
        gap = solver.gap()
        self.assertLess(gap["nash_conv_chips"], initial * .05)
        self.assertAlmostEqual(sum(gap["profile_values"]), state.pot, places=7)
        bluff = solver.distribution(parse_cards("Qd Jh"))
        self.assertTrue(.01 < bluff[1] < .99, bluff)

    def test_shared_royal_board_has_half_equity(self):
        f, t = valid_frame(board="As Ks Qs Js Ts", hero="2c 3d", facing=False)
        d = HybridPolicy().decide(f, t, BotSettings(samples=200, think_seconds=.5, max_action_chips=1), seed=1)
        self.assertEqual(d.action.kind, "check")
        self.assertAlmostEqual(d.equity, .5)

    def test_budget_stop_ledger_and_baseline_selection(self):
        f, t = valid_frame()
        with self.assertRaisesRegex(ValueError, "cancelled"):
            HybridPolicy().decide(f, t, BotSettings(), lambda: True)
        t.ledger_complete = False
        d = HybridPolicy().decide(f, t, BotSettings(samples=200, think_seconds=.2, strategy="search"))
        self.assertEqual(d.action.kind, "fold")
        self.assertEqual(d.method, "ledger-guard")
        t.ledger_complete = True
        d = HybridPolicy().decide(f, t, BotSettings(samples=200, strategy="rollout"), seed=1)
        self.assertEqual(d.method, "rollout-v1")

    def test_multi_street_routing_legality_and_budget(self):
        for board in ("", "2c 3d 7h", "2c 3d 7h 8s"):
            f, t = valid_frame(board=board, hero="As Kh")
            settings = BotSettings(samples=200, think_seconds=.3, max_action_chips=300, strategy="search")
            d = HybridPolicy().decide(f, t, settings, seed=14)
            self.assertEqual(d.method, "multi-street-rollout")
            self.assertIn(d.action, native_actions(f, t, settings))
            self.assertLess(d.elapsed_seconds, 1.5)
            self.assertGreater(d.samples, 0)

    def test_default_keeps_baseline_before_river(self):
        f, t = valid_frame(board="2c 3d 7h", hero="As Kh")
        d = HybridPolicy().decide(f, t, BotSettings(samples=200), seed=17)
        baseline = HybridPolicy().decide(f, t, BotSettings(samples=200, strategy="rollout"), seed=17)
        self.assertEqual(d.method, "rollout-v1")
        self.assertEqual(d.action, baseline.action)
        self.assertEqual(d.candidates, baseline.candidates)

    def test_tracker_records_hero_and_transition_check_without_blind_actions(self):
        f, t = valid_frame(board="2c 3d 7h", hero="As Kh", facing=False)
        after = replace(f.observation, acting_seat=3)
        t.observe(after, 1)
        self.assertEqual([(e.player_id, e.action) for e in t.public_actions], [(101, "check")])
        turn = replace(after, acting_seat=1, board=cards("2c 3d 7h 8s"))
        t.observe(turn, 1)
        self.assertEqual(t.public_actions[-1].player_id, 102)
        self.assertEqual(t.public_actions[-1].board, ("2c", "3d", "7h"))
        self.assertEqual(t.public_actions[-1].action, "check")
        self.assertEqual(t.last_raise, 50)

    def test_tracker_records_fold_when_playing_flag_clears(self):
        f, t = valid_frame(facing=False)
        old = replace(f.observation, acting_seat=3)
        t.previous = old
        after = replace(old, acting_seat=1, players=(old.players[0], replace(old.players[1], folded=True, playing=False)))
        t.observe(after, 1)
        self.assertEqual(t.public_actions[-1].action, "fold")


if __name__ == "__main__":
    unittest.main()
