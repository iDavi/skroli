"""Built-in skroli viewer (SPECS §3.3, §13).

A thin server: it serves the static UI (``assets/index.html`` + ``app.css`` +
``app.js``), exposes the config as JSON, streams feed items over a WebSocket, and
accepts config edits. No HTML/CSS/JS lives here — the browser renders everything
(feed and config forms) from data. Opens a native window via pywebview when
available (extra: ``skroli[desktop]``), otherwise prints a URL to open.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ..core.config import Config
from ..core import stream

_ASSETS = Path(__file__).parent / "assets"


def _asset(name: str) -> bytes:
    return (_ASSETS / name).read_bytes()


def config_to_dict(c: Config) -> dict:
    """The config as the browser consumes it (to render the Ingestors/Enhancers
    forms client-side)."""
    return {
        "rss": {
            "enabled": c.rss.enabled,
            "feeds": c.rss.feeds,
            "subreddits": c.rss.subreddits,
            "letterboxd": c.rss.letterboxd,
        },
        "hackernews": {"enabled": c.hn.enabled, "count": c.hn.count},
        "score": {
            "enabled": c.score.enabled,
            "half_life_hours": c.score.half_life_hours,
            "weights": c.score.weights,
        },
        "engagement": {
            "enabled": c.engagement.enabled,
            "weight": c.engagement.weight,
            "cap": c.engagement.cap,
        },
    }


class SkroliViewer:
    name = "skroli"

    def __init__(
        self,
        port: int = 4242,
        broadcaster: stream.Broadcaster | None = None,
        on_connect: Callable[[stream.Client], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
        on_save: Callable[[], None] | None = None,
        config: Config | None = None,
    ):
        self.port = port
        self._broadcaster = broadcaster or stream.Broadcaster()
        self._on_connect = on_connect
        self._on_refresh = on_refresh
        self._on_save = on_save
        self._config = config or Config()
        self._httpd: ThreadingHTTPServer | None = None

    def serve(self, open_window: bool = False) -> None:
        viewer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, body: bytes, content_type: str, status: int = 200):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json(self, payload: dict, status: int = 200):
                self._send(json.dumps(payload).encode(), "application/json", status)

            # ---- GET: static assets, config, websocket --------------------
            def do_GET(self):
                if self.path == "/ws":
                    self._serve_ws()
                elif self.path in ("/", "/index.html"):
                    self._send(_asset("index.html"), "text/html; charset=utf-8")
                elif self.path == "/app.css":
                    self._send(_asset("app.css"), "text/css; charset=utf-8")
                elif self.path == "/app.js":
                    self._send(_asset("app.js"), "application/javascript; charset=utf-8")
                elif self.path == "/api/config":
                    self._json(config_to_dict(viewer._config))
                else:
                    self.send_response(404)
                    self.end_headers()

            def _serve_ws(self):
                key = self.headers.get("Sec-WebSocket-Key")
                if not key:
                    self.send_response(400)
                    self.end_headers()
                    return
                handshake = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {stream.accept_key(key)}\r\n\r\n"
                )
                self.wfile.write(handshake.encode())
                self.wfile.flush()
                self.close_connection = True  # we own this socket now

                client = stream.Client(self.connection)
                viewer._broadcaster.add(client)
                try:
                    if viewer._on_connect:
                        viewer._on_connect(client)
                    while True:  # drain frames so we notice disconnects
                        opcode, _ = stream.read_message(self.rfile)
                        if opcode is None or opcode == 0x8:  # EOF or close
                            break
                except OSError:
                    pass
                finally:
                    viewer._broadcaster.remove(client)

            # ---- POST: refresh + config edits -----------------------------
            def _read_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    return json.loads(raw or b"{}")
                except (ValueError, TypeError):
                    return {}

            def do_POST(self):
                if self.path == "/api/refresh":
                    if viewer._on_refresh:
                        viewer._on_refresh()
                    self._json({"ok": True})
                elif self.path == "/api/ingestors":
                    data = self._read_json()
                    rss = viewer._config.rss
                    rss.enabled = bool(data.get("enabled", True))
                    rss.feeds = [str(x) for x in data.get("feeds", []) if str(x).strip()]
                    rss.subreddits = [
                        str(x).strip() for x in data.get("subreddits", []) if str(x).strip()
                    ]
                    rss.letterboxd = [
                        str(x).strip().lstrip("@") for x in data.get("letterboxd", []) if str(x).strip()
                    ]
                    self._saved()
                elif self.path == "/api/letterboxd-following":
                    from ..ingestors.rss.ingestor import letterboxd_following
                    data = self._read_json()
                    self._json({"users": letterboxd_following(str(data.get("username", "")))})
                elif self.path == "/api/hackernews":
                    data = self._read_json()
                    viewer._config.hn.enabled = bool(data.get("enabled", True))
                    try:
                        viewer._config.hn.count = max(int(data.get("count", 30)), 0)
                    except (ValueError, TypeError):
                        pass
                    self._saved()
                elif self.path == "/api/enhancers":
                    data = self._read_json()
                    score = viewer._config.score
                    score.enabled = bool(data.get("enabled", True))
                    try:
                        score.half_life_hours = max(float(data.get("half_life_hours", 12)), 0.1)
                    except (ValueError, TypeError):
                        pass
                    weights: dict[str, float] = {}
                    for k, v in (data.get("weights") or {}).items():
                        try:
                            weights[str(k)] = float(v)
                        except (ValueError, TypeError):
                            continue
                    score.weights = weights
                    self._saved()
                elif self.path == "/api/engagement":
                    data = self._read_json()
                    eng = viewer._config.engagement
                    eng.enabled = bool(data.get("enabled", True))
                    try:
                        eng.weight = min(max(float(data.get("weight", 0.4)), 0.0), 1.0)
                    except (ValueError, TypeError):
                        pass
                    try:
                        eng.cap = max(int(data.get("cap", 2000)), 1)
                    except (ValueError, TypeError):
                        pass
                    self._saved()
                else:
                    self.send_response(404)
                    self.end_headers()

            def _saved(self):
                if viewer._on_save:
                    viewer._on_save()
                self._json({"ok": True})

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        url = f"http://127.0.0.1:{self.port}"

        if open_window:
            try:
                import webview  # pywebview

                threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
                webview.create_window("skroli", url, width=1200, height=900)
                webview.start()
                return
            except ImportError:
                print("  (pywebview not installed; serving in browser instead)")

        print(f"\n  skroli is running → open {url}\n  Ctrl-C to stop.\n")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped.")
