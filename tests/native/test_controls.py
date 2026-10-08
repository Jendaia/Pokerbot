from dataclasses import replace
import unittest

from texasholdem.analyzers.native.controls import (BAR, BAR_VM, BUTTON, BUTTON_VM, SCREEN, SCREEN_VM, PokeristControls)
from texasholdem.analyzers.native.pokerist import POKER
from texasholdem.analyzers.native.runtime import RuntimeField
from native.test_pokerist import FakeTable


class ControlsTests(unittest.TestCase):
    def setUp(self):
        t = self.table = FakeTable()
        r = self.reader = t.reader
        classes = {
            "UINode": [("m_Childs", "Q"), ("m_Parent", "Q"), ("m_IsHidden", "?"), ("<Destroying>k__BackingField", "?")],
            "Children": [("m_Children", "Q")], "UIButton": [("m_IsEnabled", "?")],
            "Binding.Binder": [("m_ModelInstance", "Q")], SCREEN: [("m_ControlBar", "Q")],
            SCREEN_VM: [("<ControlBarViewModel>k__BackingField", "Q")],
            BAR_VM: [("<CurrentState>k__BackingField", "i"), ("<IsRaiseControlActiveNow>k__BackingField", "?")],
            BUTTON: [("m_Binder", "Q"), ("m_Button", "Q")],
            BUTTON_VM: [("<Type>k__BackingField", "i"), ("<Title>k__BackingField", "Q"),
                        ("<IsActive>k__BackingField", "?"), ("<IsDarkened>k__BackingField", "?"),
                        ("<ToggleMode>k__BackingField", "?"), ("<IgnoreEvents>k__BackingField", "?")],
            "Poker3DRaiseButtonWrapper": [("m_Button", "Q")],
        }
        for name, fields in classes.items():
            t.class_(name, fields, start=128 if name in ("UIButton", SCREEN, BUTTON) else 32,
                     parent="UINode" if name in ("UIButton", SCREEN, BUTTON) else None)
        node_class = r.classes["UINode"]
        r.classes["UINode"] = replace(node_class, fields=(*node_class.fields, RuntimeField("m_FinalRect", 64, 0, 0, 0x11)))
        poker = r.classes[POKER]
        r.classes[POKER] = replace(poker, fields=(*poker.fields,
            RuntimeField("m_UIPokerScreen", 352, 0, 0, 0x12), RuntimeField("m_ScreenViewModel", 360, 0, 0, 0x12),
            RuntimeField("<HandsPlayed>k__BackingField", 368, 0, 0, 8)))
        self.screen = t.object(SCREEN)
        self.bar = t.object("UINode")
        self.node = t.object(BUTTON)
        self.button = t.object("UIButton")
        self.model = t.object(BUTTON_VM)
        binder, vm, bar_vm = t.object("Binding.Binder"), t.object(SCREEN_VM), t.object(BAR_VM)
        for obj, cls, name, value in (
            (t.owner, POKER, "m_UIPokerScreen", self.screen), (t.owner, POKER, "m_ScreenViewModel", vm),
            (self.screen, SCREEN, "m_ControlBar", self.bar), (vm, SCREEN_VM, "<ControlBarViewModel>k__BackingField", bar_vm),
            (self.node, BUTTON, "m_Binder", binder), (self.node, BUTTON, "m_Button", self.button),
            (binder, "Binding.Binder", "m_ModelInstance", self.model),
            (self.bar, "UINode", "m_Parent", self.screen), (self.node, "UINode", "m_Parent", self.bar),
            (self.button, "UINode", "m_Parent", self.node),
        ): t.set(obj, cls, name, "Q", value)
        t.set(t.owner, POKER, "<HandsPlayed>k__BackingField", "i", 8)
        t.set(bar_vm, BAR_VM, "<CurrentState>k__BackingField", "i", 2)
        t.set(self.model, BUTTON_VM, "<Type>k__BackingField", "i", 3)
        t.set(self.model, BUTTON_VM, "<IsActive>k__BackingField", "?", True)
        t.set(self.button, "UIButton", "m_IsEnabled", "?", True)
        t.set(t.state, "PokerTableState", "Current", "i", 1)
        for obj, rect, children in ((self.screen, (0, 0, 1000, 600), (self.bar,)),
                                    (self.bar, (10, 20, 980, 580), (self.node,)),
                                    (self.node, (50, 500, 100, 40), (self.button,)),
                                    (self.button, (0, 0, 100, 40), ())):
            t.heap.write("<Q", obj + 16, 123)
            t.heap.write("<ffff", obj + 64, *rect)
            if children:
                collection = t.object("Children")
                t.set(collection, "Children", "m_Children", "Q", t.list(children))
                t.set(obj, "UINode", "m_Childs", "Q", collection)
        self.controls = PokeristControls.__new__(PokeristControls)
        self.controls.reader, self.controls.button_types, self.controls.states = r, {3: "CHECK"}, {2: "INSTANT_ACTIONS", 3: "DEFERRED_ACTIONS"}
        self.bar_vm = bar_vm

    def test_live_button_positions_legal_state_and_hand_counter(self):
        frame = self.controls.read()
        self.assertEqual(frame.hand_number, 8)
        self.assertEqual(frame.legal, ("check",))
        self.assertEqual(frame.buttons[0].rect, (60, 520, 100, 40))
        self.assertEqual(frame.canvas, (1000, 600))

    def test_opponent_turn_and_preselected_toggles_are_not_legal_actions(self):
        t = self.table
        t.set(t.state, "PokerTableState", "Current", "i", 3)
        self.assertEqual(self.controls.read().legal, ())
        t.set(t.state, "PokerTableState", "Current", "i", 1)
        t.set(self.model, BUTTON_VM, "<ToggleMode>k__BackingField", "?", True)
        self.assertEqual(self.controls.read().legal, ())
        t.set(self.model, BUTTON_VM, "<ToggleMode>k__BackingField", "?", False)
        t.set(self.bar_vm, BAR_VM, "<CurrentState>k__BackingField", "i", 3)
        self.assertEqual(self.controls.read().legal, ())

    def test_hidden_parent_disables_the_click_target(self):
        self.table.set(self.bar, "UINode", "m_IsHidden", "?", True)
        self.assertEqual(self.controls.read().legal, ())

    def test_raise_wrapper_is_unwrapped_before_reading_ui_fields(self):
        wrapper = self.table.object("Poker3DRaiseButtonWrapper")
        self.table.set(wrapper, "Poker3DRaiseButtonWrapper", "m_Button", "Q", self.node)
        self.assertEqual(self.controls.rect(wrapper, self.screen), (60, 520, 100, 40))
        self.assertIsNone(self.controls.rect(self.table.state, self.screen))
