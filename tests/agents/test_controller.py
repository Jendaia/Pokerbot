from dataclasses import replace
import threading
import time
import unittest

from texasholdem.agents.controller import BotController, turn_token
from texasholdem.agents.models import Action, Decision
from texasholdem.adapters.pokerist import ActionCancelled, PokeristInput
from texasholdem.adapters.x11 import canvas_point
from agents.test_policy import frame


class FakeControls:
    def __init__(self):
        self.reader = type("Reader", (), {"process": type("Process", (), {"pid": 1})()})()
        self.frame = frame()

    def read(self):
        return self.frame


class InputTests(unittest.TestCase):
    def test_stale_turn_and_stop_do_not_click(self):
        controls = FakeControls()
        clicks = []
        mouse = type("Mouse", (), {"click": lambda _, rect, canvas, guard: (guard(), clicks.append(rect))})()
        adapter = PokeristInput(controls, mouse)
        old = controls.frame
        controls.frame = replace(old, hand_number=2)
        with self.assertRaises(ActionCancelled):
            adapter.perform(Action("call"), old)
        controls.frame = old
        with self.assertRaises(ActionCancelled):
            adapter.perform(Action("call"), old, lambda: True)
        self.assertEqual(clicks, [])

    def test_stop_while_native_snapshot_is_read_does_not_click(self):
        controls, stopped = FakeControls(), False
        old_read = controls.read
        def read():
            nonlocal stopped
            stopped = True
            return old_read()
        controls.read = read
        adapter = PokeristInput(controls, object())
        with self.assertRaises(ActionCancelled):
            adapter.perform(Action("call"), controls.frame, lambda: stopped)

    def test_proton_viewport_scaling_accounts_for_borders_and_letterbox(self):
        self.assertEqual(canvas_point((1200, 676, 110, 38), (1365.333333, 768),
                         {"x": 187, "y": 210, "width": 1029, "height": 576}), (1131, 731))
        with self.assertRaises(ValueError):
            canvas_point((1400, 0, 10, 10), (1365, 768), {"x": 0, "y": 0, "width": 1000, "height": 500})

    def test_out_of_bounds_raise_is_not_confirmed(self):
        controls, clicks = FakeControls(), []
        mouse = type("Mouse", (), {"click": lambda _, rect, canvas, guard: (guard(), clicks.append(rect))})()
        adapter = PokeristInput(controls, mouse)
        with self.assertRaises(ValueError):
            adapter.perform(Action("raise", 1001), controls.frame)
        self.assertEqual(clicks, [])

    def test_raise_panel_is_dismissed_before_calling_and_permission_cache_expires(self):
        controls, clicks = FakeControls(), []
        before = replace(controls.frame, raise_open=False)
        controls.frame = replace(controls.frame, buttons=tuple(replace(b, enabled=b.action != "call") for b in before.buttons))
        def click(_, rect, canvas, guard):
            guard(); clicks.append(rect)
            if len(clicks) == 1:
                controls.frame = before
        mouse = type("Mouse", (), {"click": click})()
        adapter = PokeristInput(controls, mouse)
        adapter.base_frame = before
        prepared = adapter.with_base_buttons(controls.frame)
        self.assertIn("call", prepared.legal)
        adapter.perform(Action("call"), prepared)
        self.assertEqual(len(clicks), 2)
        changed = replace(controls.frame, hand_number=2, raise_open=True,
                          buttons=tuple(replace(b, enabled=False) for b in before.buttons))
        self.assertEqual(adapter.with_base_buttons(changed).legal, ())


class ControllerTests(unittest.TestCase):
    def make_controller(self, *, acknowledge=True, policy=None):
        controls = FakeControls()
        calls, event = [], threading.Event()
        class Adapter:
            def __init__(self, _): pass
            def close(self): pass
            def prepare(self, current, cancelled): return current
            def with_base_buttons(self, current): return current
            def perform(self, action, current, cancelled):
                if cancelled(): raise ActionCancelled("stopped")
                calls.append(action)
                if acknowledge:
                    cost = min(current.observation.players[0].stack, max(p.bet for p in current.observation.players) - current.observation.players[0].bet)
                    players = tuple(replace(p, stack=p.stack-cost, bet=p.bet+cost) if p.is_hero else p for p in current.observation.players)
                    controls.frame = replace(current, observation=replace(current.observation, acting_seat=3, players=players))
                event.set()
                return action.as_dict()
        class Policy:
            name = "Test policy"
            def decide(self, current, tracker, settings, cancelled):
                return Decision(Action("call"), "test", 1., .1, 200, 0., ())
        reader = type("Reader", (), {"close": lambda _: None})()
        controller = BotController(reader_factory=lambda: reader, controls_factory=lambda _: controls,
                                   input_factory=Adapter, policy=policy or Policy())
        return controller, controls, calls, event

    def test_autoplay_submits_one_action_then_waits_for_opponent(self):
        bot, controls, calls, event = self.make_controller()
        bot.start_worker(); bot.start()
        try:
            self.assertTrue(event.wait(2))
            time.sleep(.35)
            self.assertEqual(len(calls), 1)
            self.assertTrue(bot.snapshot()["history"][0]["acknowledged"])
            bot.stop()
            controls.frame = replace(controls.frame, hand_number=2, observation=replace(controls.frame.observation, acting_seat=1))
            time.sleep(.35)
            self.assertEqual(len(calls), 1)
        finally:
            bot.close()

    def test_unacknowledged_action_is_never_replayed(self):
        bot, controls, calls, event = self.make_controller(acknowledge=False)
        bot.start_worker(); bot.start()
        try:
            self.assertTrue(event.wait(2))
            time.sleep(.3)
            self.assertEqual(len(calls), 1)
            self.assertEqual(bot.snapshot()["status"], "waiting_ack")
            with self.assertRaises(ValueError):
                bot.act({"action": "call", "amount": 0, "turn_token": turn_token(controls.frame)})
        finally:
            bot.close()

    def test_manual_override_requires_fresh_turn_and_pauses_autoplay(self):
        bot, controls, calls, event = self.make_controller()
        bot.frame = controls.frame
        bot.start()
        with self.assertRaises(ValueError):
            bot.act({"action": "call", "amount": 0, "turn_token": "old"})
        result = bot.act({"action": "call", "amount": 0, "turn_token": turn_token(controls.frame)})
        self.assertFalse(result["enabled"])
        self.assertIsNotNone(bot.manual)

    def test_delayed_start_cannot_override_a_newer_stop(self):
        bot, _, _, _ = self.make_controller()
        generation = bot.snapshot()["generation"]
        bot.stop()
        with self.assertRaises(ValueError):
            bot.start(expected_generation=generation)
        self.assertFalse(bot.snapshot()["enabled"])

    def test_opponent_turn_change_or_auto_fold_does_not_acknowledge_a_call(self):
        old = frame()
        changed = replace(old, observation=replace(old.observation, acting_seat=3))
        self.assertFalse(BotController._acknowledged(changed, old, Action("call")))
        changed = replace(changed, observation=replace(changed.observation,
                          players=tuple(replace(p, folded=True) if p.is_hero else p for p in changed.observation.players)))
        self.assertFalse(BotController._acknowledged(changed, old, Action("call")))
        self.assertTrue(BotController._acknowledged(changed, old, Action("fold")))

    def test_stop_cancels_in_progress_search_before_input(self):
        started, release = threading.Event(), threading.Event()
        class BlockingPolicy:
            name = "Blocking test"
            def decide(self, current, tracker, settings, cancelled):
                started.set(); release.wait(2)
                return Decision(Action("call"), "test", 1., .1, 200, 0., ())
        bot, _, calls, _ = self.make_controller(policy=BlockingPolicy())
        bot.start_worker(); bot.start()
        try:
            self.assertTrue(started.wait(2))
            bot.stop(); release.set(); time.sleep(.2)
            self.assertEqual(calls, [])
        finally:
            release.set(); bot.close()
