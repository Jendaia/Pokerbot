from __future__ import annotations

import time
from dataclasses import replace

from ..agents.models import Action
from ..analyzers.native.controls import ControlFrame, PokeristControls
from .x11 import X11Input


class ActionCancelled(ValueError):
    pass


class PokeristInput:
    """Validate every click; never retry an unacknowledged betting action."""

    def __init__(self, controls: PokeristControls, mouse=None):
        self.controls = controls
        self.mouse = mouse or X11Input(controls.reader.process.pid)
        self.base_frame: ControlFrame | None = None

    def close(self):
        self.mouse.close()

    def _fresh(self, frame: ControlFrame, cancelled) -> ControlFrame:
        if cancelled():
            raise ActionCancelled("The action was stopped")
        current = self.controls.read()
        if cancelled():
            raise ActionCancelled("The action was stopped")
        if current.key != frame.key or not current.legal:
            raise ActionCancelled("The turn changed; the decision was discarded")
        return current

    def click(self, rect, frame, cancelled):
        if not rect:
            raise ValueError("Pokerist control is not visible")
        self.mouse.click(rect, frame.canvas, lambda: self._fresh(frame, cancelled))

    def prepare(self, frame: ControlFrame, cancelled=lambda: False) -> ControlFrame:
        """Expose native raise limits without confirming or spending chips."""
        current = self._fresh(frame, cancelled)
        if current.raise_open and (self.base_frame is None or self.base_frame.key != current.key):
            current = self.dismiss(current, cancelled)
        if "raise" in current.legal and not current.raise_open:
            self.base_frame = current
            button = next(b for b in current.buttons if b.action == "raise" and b.enabled and b.rect)
            self.click(button.rect, current, cancelled)
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                current = self._fresh(frame, cancelled)
                if current.raise_open and current.raise_confirm:
                    return self.with_base_buttons(current)
                time.sleep(.04)
            raise ValueError("Pokerist did not open its raise control")
        return self.with_base_buttons(current)

    def with_base_buttons(self, frame: ControlFrame) -> ControlFrame:
        # Pokerist disables Call while the raise panel is open. The underlying
        # turn still permits it after dismissing that panel. Preserve only the
        # verified permissions from this identical betting context.
        if frame.raise_open and self.base_frame is not None and self.base_frame.key == frame.key:
            return replace(frame, buttons=self.base_frame.buttons)
        return frame

    def dismiss(self, frame: ControlFrame, cancelled=lambda: False) -> ControlFrame:
        current = self._fresh(frame, cancelled)
        if current.raise_open:
            cw, ch = current.canvas
            # A neutral point on the felt, outside the raise/action controls.
            # No betting action is sent until native state confirms dismissal.
            self.click((cw * .5, ch * .56, 1., 1.), current, cancelled)
            deadline = time.monotonic() + 1.
            while time.monotonic() < deadline:
                current = self._fresh(frame, cancelled)
                if not current.raise_open:
                    self.base_frame = current
                    return current
                time.sleep(.04)
            raise ValueError("Pokerist did not dismiss its raise control")
        return current

    def perform(self, action: Action, frame: ControlFrame, cancelled=lambda: False) -> dict:
        current = self._fresh(frame, cancelled)
        if action.kind not in current.legal and current.raise_open and action.kind in frame.legal:
            current = self.dismiss(current, cancelled)
        if action.kind not in current.legal:
            raise ValueError("That action is not currently legal")
        button = next(b for b in current.buttons if b.action == action.kind and b.enabled and b.rect)
        if action.kind != "raise":
            self.click(button.rect, current, cancelled)
            return {"action": action.kind, "amount": 0}
        if not current.raise_open:
            self.click(button.rect, current, cancelled)
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                current = self._fresh(frame, cancelled)
                if current.raise_open and current.raise_confirm:
                    break
                time.sleep(.04)
            else:
                raise ValueError("Pokerist did not open its raise control")
        if current.raise_min is None or current.raise_max is None or not current.raise_min <= action.amount <= current.raise_max:
            raise ValueError("The raise is outside Pokerist's current minimum and maximum")
        if current.raise_steps and action.amount not in current.raise_steps:
            raise ValueError("Select one of Pokerist's available raise amounts")
        if not current.raise_confirm:
            raise ValueError("Pokerist's raise confirmation control is unavailable")
        # Pokerist's slider is nonlinear and rounds to native bet steps.
        # Use its own +/- controls and verify the exact amount before confirm.
        deadline, steps = time.monotonic() + 4, 0
        if current.raise_steps and current.raise_all_in and current.raise_value != action.amount:
            values = current.raise_steps
            current_index = min(range(len(values)), key=lambda i: abs(values[i] - current.raise_value))
            target_index = values.index(action.amount)
            if len(values) - 1 - target_index + 1 < abs(target_index - current_index):
                self.click(current.raise_all_in, current, cancelled)
                time.sleep(.055)
                current = self._fresh(frame, cancelled)
        while current.raise_value != action.amount:
            if time.monotonic() >= deadline or steps >= 48:
                raise ValueError("Pokerist could not select the exact requested raise")
            previous = current.raise_value
            if action.amount == current.raise_max and current.raise_all_in:
                rect = current.raise_all_in
            else:
                rect = current.raise_increase if previous < action.amount else current.raise_decrease
            self.click(rect, current, cancelled)
            steps += 1
            time.sleep(.055)
            current = self._fresh(frame, cancelled)
            if current.raise_value == previous:
                raise ValueError("Pokerist did not update the raise amount")
            if (previous < action.amount < current.raise_value) or (current.raise_value < action.amount < previous):
                raise ValueError("That amount is not one of Pokerist's available bet steps")
        # Confirm only after a second amount/turn verification inside the guard.
        def guard():
            latest = self._fresh(frame, cancelled)
            if not latest.raise_open or latest.raise_value != action.amount or latest.raise_confirm != current.raise_confirm:
                raise ActionCancelled("Raise controls changed before confirmation")
        self.mouse.click(current.raise_confirm, current.canvas, guard)
        return {"action": "raise", "amount": action.amount}
