from http.client import HTTPConnection
from contextlib import closing
import json
import threading
import unittest

from texasholdem.dashboard.server import DashboardServer
from texasholdem.dashboard.service import DashboardService
from native.test_observation import observation


class DashboardServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = DashboardService()
        cls.service.publish(observation())
        cls.server = DashboardServer(0, cls.service)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        with closing(HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)) as connection:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()

    def test_live_snapshot_and_packaged_assets(self):
        status, headers, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)["observation"]["acting_player_id"], 102)
        for path in ("/", "/app.js", "/styles.css", "/mark.svg"):
            status, _, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertTrue(body)

    def test_scenario_endpoint(self):
        status, _, body = self.request("POST", "/api/analyze", json.dumps({
            "hero": "As Ks", "board": "Qs Js Ts 2d 3c", "opponents": 1,
        }), {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["result"]["equity"]["win_percentage"], 100)
        self.assertEqual(self.service.snapshot()["observation"]["hero_id"], 101)

    def test_invalid_card_request_is_json_error(self):
        status, _, body = self.request("POST", "/api/analyze", '{"hero":"As As"}', {"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertIn("Duplicate", json.loads(body)["error"])

    def test_no_arbitrary_file_serving_or_remote_origins(self):
        for path in ("/../../pyproject.toml", "/src/texasholdem/dashboard/server.py"):
            self.assertEqual(self.request("GET", path)[0], 404)
        for headers in ({"Origin": "https://example.com"}, {"Host": "example.com"}, {"Origin": "http://localhost:bad"}):
            self.assertEqual(self.request("GET", "/api/state", headers=headers)[0], 403)

    def test_autoplay_settings_start_stop_and_remote_requests_rejected(self):
        headers = {"Content-Type": "application/json"}
        status, _, body = self.request("POST", "/api/bot/start", '{"max_action_chips":100}', headers)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["bot"]["enabled"])
        status, _, body = self.request("POST", "/api/bot/stop", '{}', headers)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["bot"]["enabled"])
        self.assertEqual(self.request("POST", "/api/bot/start", '{"samples":true}', headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/bot/action", '{"action":"call","amount":0,"turn_token":"stale"}', headers)[0], 400)
        self.assertEqual(self.request("POST", "/api/bot/start", '{}', {**headers, "Origin": "http://attacker.example"})[0], 403)

    def test_unlimited_objective_settings_apply_with_generation_without_starting(self):
        headers = {"Content-Type": "application/json"}
        self.service.bot.stop()
        generation = self.service.bot.generation
        settings = {"objective": "conservative", "max_action_chips": None, "max_hands": None,
                    "stop_loss_chips": None, "expected_generation": generation}
        status, _, body = self.request("POST", "/api/bot/settings", json.dumps(settings), headers)
        self.assertEqual(status, 200)
        bot = json.loads(body)["bot"]
        self.assertFalse(bot["enabled"])
        self.assertEqual(bot["settings"]["objective"], "conservative")
        self.assertIsNone(bot["settings"]["max_action_chips"])
        self.assertEqual(self.request("POST", "/api/bot/settings", json.dumps(settings), headers)[0], 400)
        for invalid in ({"objective": "money"}, {"samples": None}, {"max_hands": False}):
            status, _, _ = self.request("POST", "/api/bot/settings", json.dumps({**invalid, "expected_generation": bot["generation"]}), headers)
            self.assertEqual(status, 400)
        self.assertEqual(self.request("POST", "/api/bot/settings", '{}', headers)[0], 400)
