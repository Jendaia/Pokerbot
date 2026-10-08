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
