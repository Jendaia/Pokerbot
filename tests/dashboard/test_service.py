from dataclasses import replace
import threading
import unittest

from texasholdem.dashboard.service import DashboardService
from native.test_observation import cards, observation


class DashboardServiceTests(unittest.TestCase):
    def test_spectator_snapshot_and_copy_isolation(self):
        service = DashboardService()
        service.publish(replace(observation(), spectating=True, hero_id=None, hero_cards=()))
        snapshot = service.snapshot()
        self.assertEqual(snapshot["connection"]["status"], "live")
        self.assertEqual(snapshot["analysis"]["status"], "unavailable")
        self.assertEqual(snapshot["observation"]["hero_cards"], ())
        snapshot["observation"]["table_id"] = 999
        self.assertEqual(service.snapshot()["observation"]["table_id"], 22)

    def test_disconnection_clears_live_cards_and_odds(self):
        service = DashboardService()
        service.publish(observation())
        service.disconnected("Reconnecting")
        snapshot = service.snapshot()
        self.assertIsNone(snapshot["observation"])
        self.assertEqual(snapshot["analysis"]["status"], "unavailable")
        self.assertIsNone(service.desired)

    def test_older_calculation_cannot_overwrite_new_hand_and_cache_reused(self):
        started, release = threading.Event(), threading.Event()
        calls = []

        def calculator(state, **_):
            calls.append(tuple(map(str, state.hero)))
            if len(calls) == 1:
                started.set()
                release.wait(2)
            return {"hero": list(map(str, state.hero))}

        service = DashboardService(analyzer=calculator)
        worker = threading.Thread(target=service._analysis_loop, daemon=True)
        service.threads.append(worker)
        worker.start()
        try:
            service.publish(observation())
            self.assertTrue(started.wait(1))
            next_hand = replace(observation(), hero_cards=cards("Ah Kh"))
            service.publish(next_hand)
            self.assertEqual(service.snapshot()["analysis"]["status"], "calculating")
            release.set()
            with service.condition:
                self.assertTrue(service.condition.wait_for(lambda: service.payload["analysis"]["status"] == "ready", timeout=2))
            self.assertEqual(service.snapshot()["analysis"]["result"]["hero"], ["Ah", "Kh"])
            service.publish(replace(next_hand, collected_pot=1000))
            self.assertEqual(service.snapshot()["analysis"]["status"], "ready")
            self.assertEqual(len(calls), 2)
        finally:
            release.set()
            service.close()

    def test_round_log_only_records_observed_transitions(self):
        service = DashboardService()
        sample = replace(observation(), spectating=True)
        service.publish(sample)
        service.publish(replace(sample, acting_seat=1, collected_pot=400,
                                players=tuple(replace(p, folded=True) if p.id == 102 else p for p in sample.players)))
        events = [event["message"] for event in service.snapshot()["events"]]
        self.assertIn("Opponent folded", events)
        self.assertIn("Hero to act · seat 1", events)
        self.assertIn("Pot updated to 575", events)
        self.assertFalse(any("raised" in event.lower() for event in events))
