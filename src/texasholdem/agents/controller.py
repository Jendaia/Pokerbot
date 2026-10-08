from __future__ import annotations

from collections import deque
from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from ..adapters.pokerist import ActionCancelled, PokeristInput
from ..analyzers.native import PokeristReader
from ..analyzers.native.controls import PokeristControls
from .models import Action, BotSettings
from .opponents import HandTracker
from .strategy import HybridPolicy


def turn_token(frame) -> str:
    return sha256(repr(frame.key).encode()).hexdigest()[:24]


class BotController:
    """One input owner, cancellable planning, fresh-turn checks, and acknowledgments."""

    def __init__(self, *, pid=None, table_id=None, reader_factory=None, controls_factory=PokeristControls,
                 input_factory=PokeristInput, policy=None, audit_dir: Path | None = None):
        self.reader_factory = reader_factory or (lambda: PokeristReader(pid, table_id=table_id))
        self.controls_factory, self.input_factory = controls_factory, input_factory
        self.policy = policy or HybridPolicy()
        self.audit_dir = audit_dir
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.enabled, self.generation = False, 0
        self.settings = BotSettings()
        self.bound_table = None
        self.baseline = None
        self.hands = set()
        self.actions = 0
        self.session_id = uuid4().hex
        self.manual = None
        self.frame = None
        self.history = deque(maxlen=30)
        self.payload = {"enabled": False, "status": "connecting", "message": "Connecting to game controls",
                        "strategy": self.policy.name, "settings": self.settings.as_dict(), "controls": None,
                        "decision": None, "session": {"hands": 0, "actions": 0, "net_chips": None},
                        "history": [], "opponents": {}}

    def start_worker(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="poker-autoplay", daemon=True)
            self.thread.start()

    def close(self):
        self.stop("Dashboard closed")
        self.stopped.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=6)

    def snapshot(self):
        with self.lock:
            return {**deepcopy(self.payload), "generation": self.generation}

    def _status(self, status, message):
        with self.lock:
            self.payload.update(enabled=self.enabled, status=status, message=message)

    def start(self, settings: dict | None = None, *, expected_generation: int | None = None):
        chosen = BotSettings.from_dict(settings or self.settings.as_dict())
        with self.lock:
            if expected_generation is not None and (type(expected_generation) is not int or expected_generation != self.generation):
                raise ValueError("The controller changed; refresh before starting autoplay")
            self.settings = chosen
            self.enabled = True
            self.generation += 1
            self.manual = None
            self.bound_table, self.baseline = None, None
            self.hands, self.actions = set(), 0
            self.session_id = uuid4().hex
            self.payload["settings"] = chosen.as_dict()
            self.payload["decision"] = None
            self.payload["session"] = {"hands": 0, "actions": 0, "net_chips": None}
            self._status("waiting", "Autoplay active · waiting for your next legal turn")
        self.wake.set()
        return self.snapshot()

    def stop(self, message="Autoplay stopped"):
        with self.lock:
            self.enabled = False
            self.generation += 1
            self.manual = None
            self._status("stopped", message)
        self.wake.set()
        return self.snapshot()

    def act(self, data: dict):
        if not isinstance(data, dict) or set(data) != {"action", "amount", "turn_token"}:
            raise ValueError("Send action, amount, and the displayed turn_token")
        action = Action(data["action"], data["amount"])
        with self.lock:
            if self.frame is None or data["turn_token"] != turn_token(self.frame) or action.kind not in self.frame.legal:
                raise ValueError("The displayed turn has changed or that move is not legal")
            if self.manual or self.payload["status"] in ("acting", "waiting_ack"):
                raise ValueError("A manual action is already pending")
            self.enabled = False
            self.generation += 1
            self.manual = (action, self.frame.key, self.generation)
            self._status("waiting", "Manual action queued · autoplay paused")
        self.wake.set()
        return self.snapshot()

    def prepare(self, data: dict):
        if not isinstance(data, dict) or set(data) != {"turn_token"}:
            raise ValueError("Send the displayed turn_token")
        with self.lock:
            if self.frame is None or data["turn_token"] != turn_token(self.frame) or "raise" not in self.frame.legal:
                raise ValueError("The turn changed or a raise is not legal")
            if self.manual or self.payload["status"] in ("acting", "waiting_ack"):
                raise ValueError("Another action is pending")
            self.enabled = False
            self.generation += 1
            self.manual = (None, self.frame.key, self.generation)
            self._status("waiting", "Opening native raise controls · autoplay paused")
        self.wake.set()
        return self.snapshot()

    def _cancelled(self, generation):
        with self.lock:
            return self.stopped.is_set() or generation != self.generation

    def _record(self, frame, action, decision, result, tracker=None):
        entry = {"id": uuid4().hex, "session_id": self.session_id,
                 "at": datetime.now(timezone.utc).isoformat(), "table_id": frame.observation.table_id,
                 "hand_number": frame.hand_number, "hero_cards": [c.code for c in frame.observation.hero_cards],
                 "board": [c.code for c in frame.observation.board], "pot": frame.observation.pot_total,
                 "action": action.as_dict(), "decision": decision.as_dict() if decision else None,
                 "input": result, "acknowledged": False, "observation": frame.observation.as_dict(),
                 "public_history": [asdict(event) for event in tracker.public_actions] if tracker else []}
        with self.lock:
            self.history.appendleft(entry)
            self.actions += 1
            self.payload["history"] = list(self.history)
            self.payload["session"]["actions"] = self.actions
        self._audit(entry, "submitted")
        return entry

    def _audit(self, entry, event):
        if self.audit_dir is not None:
            try:
                self.audit_dir.mkdir(parents=True, exist_ok=True)
                target = self.audit_dir / (datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".jsonl")
                with target.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({**entry, "event": event}, allow_nan=False) + "\n")
            except OSError:
                # Losing audit storage does not justify replaying an input.
                pass

    @staticmethod
    def _acknowledged(frame, old, action):
        now, previous = frame.observation, old.observation
        hero = next((p for p in now.players if p.id == previous.hero_id), None)
        before = next(p for p in previous.players if p.id == previous.hero_id)
        if now.table_id != previous.table_id or frame.hand_number != old.hand_number or not now.game_in_progress or now.result_in_progress:
            return True
        if hero is None:
            return action.kind == "fold"
        if action.kind == "fold":
            return hero.folded
        if hero.folded:
            return False
        if action.kind == "check":
            return now.acting_player_id != previous.hero_id
        cost = (min(before.stack, max(p.bet for p in previous.players) - before.bet)
                if action.kind == "call" else action.amount)
        return hero.stack <= before.stack - cost or hero.bet >= before.bet + cost

    def _loop(self):
        reader = controls = adapter = None
        tracker = HandTracker()
        pending = None
        submitted = deque(maxlen=1000)
        failures = 0
        try:
            while not self.stopped.is_set():
                operation = "read"
                try:
                    if reader is None:
                        reader = self.reader_factory()
                        controls = self.controls_factory(reader)
                    frame = controls.read()
                    if adapter:
                        frame = adapter.with_base_buttons(frame)
                    failures = 0
                    tracker.observe(frame.observation, frame.hand_number)
                    with self.lock:
                        self.frame = frame
                        self.payload["controls"] = {**frame.as_dict(), "turn_token": turn_token(frame)}
                        self.payload["opponents"] = {str(id_): p.as_dict() for id_, p in tracker.profiles.items()}
                        enabled, generation, settings, manual = self.enabled, self.generation, self.settings, self.manual
                    if pending:
                        old, action, entry, sent_at = pending
                        if self._acknowledged(frame, old, action):
                            with self.lock:
                                entry["acknowledged"] = True
                                self.payload["history"] = list(self.history)
                            self._audit(entry, "acknowledged")
                            pending = None
                            self._status("waiting" if enabled else "stopped", "Action confirmed · waiting for the next turn" if enabled else "Manual action confirmed · autoplay paused")
                        elif time.monotonic() - sent_at > 6:
                            entry["error"] = "Action acknowledgment timed out; no retry was sent"
                            self._audit(entry, "failed")
                            self.stop(entry["error"])
                            pending = None
                        else:
                            self.stopped.wait(.1)
                            continue
                    if not enabled and not manual:
                        if self.payload["status"] == "connecting":
                            self._status("stopped", "Controls ready · autoplay is stopped")
                        self.wake.wait(.25)
                        self.wake.clear()
                        continue
                    observation = frame.observation
                    hero = next((p for p in observation.players if p.is_hero), None)
                    if enabled:
                        with self.lock:
                            if self.bound_table is None and hero:
                                self.bound_table = observation.table_id
                                self.baseline = hero.stack + hero.bet + tracker.committed.get(hero.id, 0)
                            if self.bound_table is not None and observation.table_id != self.bound_table:
                                self.stop("Table changed · start a new session to continue")
                                continue
                            if hero and hero.playing and not hero.folded and observation.game_in_progress and not observation.result_in_progress:
                                self.hands.add((observation.table_id, frame.hand_number))
                            net = (hero.stack + hero.bet + tracker.committed.get(hero.id, 0) - self.baseline) if hero and self.baseline is not None else None
                            self.payload["session"].update(hands=len(self.hands), net_chips=net)
                            if len(self.hands) > settings.max_hands:
                                self.stop("The configured hand limit was reached")
                                continue
                            if net is not None and observation.street == "pre-flop" and net <= -settings.stop_loss_chips:
                                self.stop("The configured session loss limit was reached")
                                continue
                            if hero and hero.stack == 0 and not observation.game_in_progress:
                                self.stop("The table stack is empty · session finished")
                                continue
                    if not frame.legal or hero is None:
                        self._status("waiting", "Waiting for your turn" if hero and not observation.spectating else "Waiting for a seated Texas Hold’em player")
                        self.stopped.wait(.25)
                        continue
                    if frame.key in submitted:
                        self.stopped.wait(.1)
                        continue
                    cancelled = lambda: self._cancelled(generation)
                    if adapter is None:
                        adapter = self.input_factory(controls)
                    operation = "input"
                    decision = None
                    if manual:
                        action, expected, requested_generation = manual
                        if expected != frame.key or requested_generation != generation:
                            self.stop("Manual action discarded because the turn changed")
                            continue
                        if action is None or action.kind == "raise":
                            frame = adapter.prepare(frame, cancelled)
                        with self.lock:
                            self.manual = None
                        if action is None:
                            self._status("stopped", "Raise controls opened · select an amount and confirm Raise")
                            continue
                    else:
                        observation.to_game_state()
                        self._status("thinking", "Evaluating legal actions against estimated opponent ranges")
                        frame = adapter.prepare(frame, cancelled)
                        decision = self.policy.decide(frame, tracker, settings, cancelled)
                        action = decision.action
                        with self.lock:
                            if cancelled():
                                continue
                            self.payload["decision"] = decision.as_dict()
                    if cancelled():
                        continue
                    self._status("acting", f"Submitting {action.kind}" + (f" · {action.amount:,} chips" if action.amount else ""))
                    result = adapter.perform(action, frame, cancelled)
                    submitted.append(frame.key)
                    entry = self._record(frame, action, decision, result, tracker)
                    pending = (frame, action, entry, time.monotonic())
                    self._status("waiting_ack", "Mouse input sent · waiting for Pokerist to confirm")
                except ActionCancelled:
                    self._status("waiting" if self.enabled else "stopped", "Turn changed or playback stopped; decision discarded")
                except (ValueError, OSError, ModuleNotFoundError) as error:
                    if operation != "read" and 'generation' in locals() and self._cancelled(generation):
                        continue
                    if (self.enabled or self.manual) and operation != "read":
                        # A transient read race is common at transitions. An
                        # input or policy error, however, must stop immediately.
                        if "changed while" not in str(error):
                            self.stop(str(error))
                    failures += 1
                    if failures >= 5 or reader is None:
                        if self.enabled and self.bound_table is not None:
                            self.stop("The live game connection was lost; no more input will be sent")
                        self._status("disconnected", str(error))
                        with self.lock:
                            self.frame = None
                            self.payload["controls"] = None
                        if adapter:
                            adapter.close()
                            adapter = None
                        if reader:
                            reader.close()
                            reader = None
                        self.stopped.wait(1)
                    else:
                        self.stopped.wait(.1)
                except Exception as error:
                    self.stop(f"Autoplay failed: {type(error).__name__}: {error}")
                    self.stopped.wait(.5)
        finally:
            if adapter:
                adapter.close()
            if reader:
                reader.close()
