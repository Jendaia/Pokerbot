from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import threading
from urllib.parse import urlsplit

from .analysis import analyze_state, scenario_state
from .service import DashboardService


ASSETS = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/mark.svg": ("mark.svg", "image/svg+xml")}


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, service: DashboardService):
        self.service = service
        self.scenario_lock = threading.Lock()
        super().__init__(("127.0.0.1", port), DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, *_):
        pass

    def _local_request(self) -> bool:
        try:
            authority = urlsplit("http://" + self.headers.get("Host", "")).hostname
            origin = self.headers.get("Origin")
            allowed = authority in ("127.0.0.1", "localhost")
            if origin:
                parsed = urlsplit(origin)
                allowed = allowed and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost") and parsed.port == self.server.server_port
        except ValueError:
            allowed = False
        if not allowed:
            self._json({"error": "This dashboard is available locally only"}, 403)
        return allowed

    def _send(self, data: bytes, mime: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data: dict, status: int = 200) -> None:
        self._send(json.dumps(data, ensure_ascii=False, allow_nan=False).encode(), "application/json; charset=utf-8", status)

    def do_GET(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/state":
            self._json(self.server.service.snapshot())
        elif path in ASSETS:
            filename, mime = ASSETS[path]
            self._send(files("texasholdem.dashboard").joinpath("static", filename).read_bytes(), mime)
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        if path not in ("/api/analyze", "/api/bot/start", "/api/bot/stop", "/api/bot/action", "/api/bot/prepare"):
            self._json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("The calculation request is empty or too large")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError("Send the hand as JSON")
            self.connection.settimeout(5)
            payload = json.loads(self.rfile.read(length))
            if path.startswith("/api/bot/"):
                if not isinstance(payload, dict):
                    raise ValueError("Send a JSON object")
                bot = self.server.service.bot
                if path == "/api/bot/start":
                    expected_generation = payload.pop("expected_generation", None)
                    result = bot.start(payload, expected_generation=expected_generation)
                elif path == "/api/bot/stop":
                    if payload:
                        raise ValueError("Stop takes an empty JSON object")
                    result = bot.stop()
                elif path == "/api/bot/action":
                    result = bot.act(payload)
                else:
                    result = bot.prepare(payload)
                self._json({"bot": result})
                return
            state, simulations = scenario_state(payload)
        except (ValueError, OSError, UnicodeError) as error:
            self._json({"error": str(error)}, 400)
            return
        if not self.server.scenario_lock.acquire(blocking=False):
            self._json({"error": "Another scenario is calculating. Try again in a moment."}, 429)
            return
        try:
            self._json({"status": "ready", "source": "scenario", "result": analyze_state(state, simulations=simulations)})
        except Exception:
            self._json({"error": "The calculation failed. Check your cards and try again."}, 500)
        finally:
            self.server.scenario_lock.release()
