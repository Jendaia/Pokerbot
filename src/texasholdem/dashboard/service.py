from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
import json
from math import isfinite
import threading
from typing import Callable

from ..analyzers.native import PokeristReader
from ..core.game_state import GameState
from ..models.observation import TableObservation
from .analysis import analyze_state, round_metrics


def state_key(state: GameState) -> str:
    return json.dumps(state.as_dict(), sort_keys=True)


class DashboardService:
    """Read the game independently of slow calculations and browser requests."""

    def __init__(self, *, pid: int | None = None, table_id: int | None = None,
                 interval: float = 0.5, simulations: int = 10_000,
                 reader_factory: Callable | None = None, analyzer: Callable = analyze_state):
        if not isfinite(interval) or interval <= 0:
            raise ValueError("Refresh interval must be finite and positive")
        if type(simulations) is not int or not 1_000 <= simulations <= 50_000:
            raise ValueError("Choose between 1,000 and 50,000 samples")
        self.interval, self.simulations = interval, simulations
        self.reader_factory = reader_factory or (lambda: PokeristReader(pid, table_id=table_id))
        self.analyzer = analyzer
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.threads: list[threading.Thread] = []
        self.desired: tuple[str, GameState] | None = None
        self.completed_key: str | None = None
        self.previous: TableObservation | None = None
        self.events: deque[dict] = deque(maxlen=40)
        self.sequence = 0
        self.payload = {
            "connection": {"status": "connecting", "message": "Connecting to Pokerist…"},
            "observation": None, "metrics": None,
            "analysis": {"status": "unavailable", "reason": "Waiting for a table"},
            "events": [], "refresh_seconds": interval,
        }

    def start(self) -> None:
        if self.threads:
            return
        for name, target in (("poker-reader", self._read_loop), ("poker-analysis", self._analysis_loop)):
            thread = threading.Thread(name=name, target=target, daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self) -> None:
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        for thread in self.threads:
            thread.join(timeout=5)

    def snapshot(self) -> dict:
        with self.condition:
            return deepcopy(self.payload)

    def _event(self, message: str, kind: str = "round") -> None:
        self.sequence += 1
        self.events.appendleft({"id": self.sequence, "at": datetime.now(timezone.utc).isoformat(),
                                "message": message, "kind": kind})

    def _track(self, observation: TableObservation) -> None:
        old = self.previous
        if old is None or old.table_id != observation.table_id:
            self.events.clear()
            self._event(f"Connected to table {observation.table_id}", "connection")
        else:
            before, after = {p.id: p for p in old.players}, {p.id: p for p in observation.players}
            for id_ in after.keys() - before.keys():
                self._event(f"{after[id_].name or 'Player'} joined seat {after[id_].seat}", "player")
            for id_ in before.keys() - after.keys():
                self._event(f"{before[id_].name or 'Player'} left the table", "player")
            for id_ in before.keys() & after.keys():
                if after[id_].folded and not before[id_].folded:
                    self._event(f"{after[id_].name or 'Player'} folded", "player")
            if old.stage != observation.stage:
                self._event(f"{observation.stage.replace('-', ' ').title()}" + (
                    " · " + " ".join(card.code or "?" for card in observation.board) if observation.board else ""))
            if old.acting_player_id != observation.acting_player_id and observation.acting_player_id is not None:
                acting = after.get(observation.acting_player_id)
                if acting:
                    self._event(f"{acting.name or 'Player'} to act · seat {acting.seat}", "turn")
            if old.pot_total != observation.pot_total:
                self._event(f"Pot updated to {observation.pot_total:,.0f}", "pot")
        self.previous = observation

    def publish(self, observation: TableObservation) -> None:
        """Publish a fresh table and schedule only the most recent valid hand."""
        try:
            state = observation.to_game_state()
        except ValueError as error:
            state, reason = None, str(error)
        with self.condition:
            self._track(observation)
            self.payload.update({
                "connection": {"status": "live", "message": "Connected to Pokerist"},
                "observation": observation.as_dict(), "metrics": round_metrics(observation),
                "events": list(self.events),
            })
            if state is None:
                self.desired = None
                self.payload["analysis"] = {"status": "unavailable", "reason": reason}
            else:
                key = state_key(state)
                if self.desired is None or self.desired[0] != key:
                    self.desired = key, state
                    self.completed_key = None
                    self.payload["analysis"] = {"status": "calculating", "key": key}
            self.condition.notify_all()

    def disconnected(self, message: str) -> None:
        with self.condition:
            self.desired = None
            self.previous = None
            self.payload.update({
                "connection": {"status": "reconnecting", "message": message},
                "observation": None, "metrics": None,
                "analysis": {"status": "unavailable", "reason": "Waiting for a live table"},
            })
            self.condition.notify_all()

    def _read_loop(self) -> None:
        reader = None
        while not self.stopped.is_set():
            try:
                if reader is None:
                    reader = self.reader_factory()
                self.publish(reader.read())
            except (OSError, ValueError, ModuleNotFoundError) as error:
                if reader is not None:
                    reader.close()
                    reader = None
                message = "Open Pokerist and enter a table. Reconnecting automatically."
                if isinstance(error, PermissionError):
                    message = "The game process cannot be read by this user. Restart the dashboard from the same account."
                elif isinstance(error, ModuleNotFoundError):
                    message = "Install the native reader with: pip install -e '.[native]'"
                self.disconnected(message)
                self.stopped.wait(2)
            else:
                self.stopped.wait(self.interval)
        if reader is not None:
            reader.close()

    def _analysis_loop(self) -> None:
        while not self.stopped.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.stopped.is_set() or (
                    self.desired is not None and self.desired[0] != self.completed_key))
                if self.stopped.is_set():
                    return
                key, state = self.desired
            try:
                result = self.analyzer(state, simulations=self.simulations)
                analysis = {"status": "ready", "key": key, "result": result}
            except Exception:
                analysis = {"status": "error", "key": key, "reason": "The calculation failed. Try the next hand."}
            with self.condition:
                if self.desired is not None and self.desired[0] == key:
                    self.payload["analysis"] = analysis
                    self.completed_key = key
                    self.condition.notify_all()
