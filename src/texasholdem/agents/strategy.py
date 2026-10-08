from __future__ import annotations

import random
import time

from .models import Decision
from .policy import RolloutPolicy


class HybridPolicy:
    """Research-informed default, with the original rollout retained for A/B."""
    name = "River CFR+ / range rollout"

    def decide(self, frame, tracker, settings, cancelled=lambda: False, *, seed=None):
        started = time.monotonic()
        if settings.strategy == "rollout":
            return RolloutPolicy().decide(frame, tracker, settings, cancelled, seed=seed)
        # Lazy imports keep the standard-library calculator usable without the
        # optional native/strategy NumPy dependency.
        from .search.betting import BettingState, native_actions
        from .search.ranges import range_space
        from .search.river import RiverSolver
        from .search.rollout import MultiStreetPolicy
        o = frame.observation
        gs = o.to_game_state()
        if o.acting_player_id != o.hero_id or not frame.legal:
            raise ValueError("The hero does not have a legal turn")
        actions = native_actions(frame, tracker, settings)
        state = BettingState.from_frame(frame, tracker)
        if len(gs.board) == 5 and len(state.live) == 2 and tracker.ledger_complete:
            space = range_space(gs.board)
            other = next(i for i in state.live if i != state.actor)
            ranges = [space.weights(tracker, state.ids[i]) for i in (state.actor, other)]
            solver = RiverSolver(state, space, ranges, actions, cap=settings.max_action_chips)
            # Leave room for average-strategy value/gap diagnostics and native
            # validation. Time covers range and tree construction as well.
            solver.solve(settings.samples, deadline=started + settings.think_seconds * .85, cancelled=cancelled)
            if solver.iterations:
                probabilities = solver.distribution(gs.hero)
                values = solver.action_values(gs.hero)
                gap = solver.gap()
                if cancelled():
                    raise ValueError("Decision was cancelled")
                selected = random.Random(seed).choices(range(len(actions)), weights=probabilities, k=1)[0]
                index = space.index[tuple(sorted(gs.hero))]
                win, tie, lose = space.outcome_mass(ranges[1])
                equity = float((win[index] + .5 * tie[index]) / (win[index] + tie[index] + lose[index]))
                candidates = tuple({"action": a.kind, "amount": a.amount, "ev_chips": float(values[i]),
                                    "standard_error": None, "score": float(values[i]), "probability": float(probabilities[i])}
                                   for i, a in enumerate(actions))
                return Decision(actions[selected], f"River CFR+ · {solver.iterations:,} iterations · sampled from the mixed strategy",
                                equity, state.call / max(1, state.pot + state.call), solver.iterations,
                                time.monotonic() - started, candidates, "river-cfr+",
                                {**gap, "iterations": solver.iterations, "nodes": solver.nodes,
                                 "combos_per_player": len(space.hands), "history_actions": len(tracker.public_actions),
                                 "limitations": "Gap applies only to this restricted river tree and estimated ranges; not full-game exploitability"})
        if settings.strategy == "search":
            return MultiStreetPolicy().decide(frame, tracker, settings, cancelled, seed=seed, started=started)
        # The multi-street prototype did not clear the paired arena gate.
        # Keep the measured baseline on earlier streets and multiway rivers;
        # do not promote an algorithm just because it searches a bigger tree.
        return RolloutPolicy().decide(frame, tracker, settings, cancelled, seed=seed)
