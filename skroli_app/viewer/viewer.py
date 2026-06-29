"""Built-in skroli viewer (SPECS §3.3, §13).

A thin, addon-agnostic server. It serves the static UI (``assets/index.html`` +
``app.css`` + ``app.js``), exposes the config as a generic list of sections
(each addon describes its own fields), streams feed items over a WebSocket, and
applies config edits + named actions back to the addons. It never references a
specific ingestor or enhancer. Opens a native window via pywebview when
available (extra: ``skroli[desktop]``), otherwise prints a URL to open.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from ..core.addons_base import Section
from ..core import stream

_ASSETS = Path(__file__).parent / "assets"


def _asset(name: str) -> bytes:
    return (_ASSETS / name).read_bytes()


def _section_form(config, section: Section) -> dict:
    target = getattr(config, section.attr)
    return {
        "id": section.id,
        "group": section.group,
        "title": section.title,
        "desc": section.desc,
        "fields": [asdict(f) for f in section.fields],
        "values": {f.key: getattr(target, f.key) for f in section.fields},
    }


def _apply_values(config, section: Section, values: dict) -> None:
    """Write submitted form values back onto the addon's config dataclass,
    coercing by each field's declared kind."""
    target = getattr(config, section.attr)
    for f in section.fields:
        if f.key not in values:
            continue
        v = values[f.key]
        try:
            if f.kind == "toggle":
                setattr(target, f.key, bool(v))
            elif f.kind == "int":
                n = int(v)
                setattr(target, f.key, max(n, int(f.min)) if f.min is not None else n)
            elif f.kind == "float":
                n = float(v)
                if f.min is not None:
                    n = max(n, f.min)
                if f.max is not None:
                    n = min(n, f.max)
                setattr(target, f.key, n)
            elif f.kind == "list":
                out = []
                for x in v or []:
                    s = str(x).strip()
                    if f.prefix and s.startswith(f.prefix):
                        s = s[len(f.prefix):]
                    if s:
                        out.append(s)
                setattr(target, f.key, out)
            elif f.kind == "weights":
                w: dict[str, float] = {}
                for k, val in (v or {}).items():
                    try:
                        w[str(k)] = float(val)
                    except (ValueError, TypeError):
                        continue
                setattr(target, f.key, w)
        except (ValueError, TypeError):
            continue


class SkroliViewer:
    name = "skroli"

    def __init__(
        self,
        port: int = 4242,
        broadcaster: stream.Broadcaster | None = None,
        on_connect: Callable[[stream.Client], None] | None = None,
        on_refresh: Callable[[], None] | None = None,
        on_save: Callable[[], None] | None = None,
        config=None,
        sections: list[Section] | None = None,
        actions: dict[str, Callable[[dict], dict]] | None = None,
    ):
        self.port = port
        self._broadcaster = broadcaster or stream.Broadcaster()
        self._on_connect = on_connect
        self._on_refresh = on_refresh
        self._on_save = on_save
        self._config = config
        self._sections = sections or []
        self._actions = actions or {}
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

            def _json(self, payload, status: int = 200):
                self._send(json.dumps(payload).encode(), "application/json", status)

            # ---- GET: static assets, config, websocket --------------------
            def do_GET(self):
                route = self.path.split("?", 1)[0]   # ignore query (e.g. ?shell=1)
                if self.path == "/ws":
                    self._serve_ws()
                elif route in ("/", "/index.html"):
                    self._send(_asset("index.html"), "text/html; charset=utf-8")
                elif route == "/app.css":
                    self._send(_asset("app.css"), "text/css; charset=utf-8")
                elif route == "/app.js":
                    self._send(_asset("app.js"), "application/javascript; charset=utf-8")
                elif self.path == "/api/config":
                    self._json({"sections": [
                        _section_form(viewer._config, s) for s in viewer._sections
                    ]})
                elif self.path.startswith("/api/read?"):
                    from urllib.parse import urlparse, parse_qs
                    from . import reader
                    url = (parse_qs(urlparse(self.path).query).get("url") or [""])[0]
                    self._json(reader.read_url(url))
                elif self.path.startswith("/proxy?"):
                    from urllib.parse import urlparse, parse_qs
                    from . import reader
                    url = (parse_qs(urlparse(self.path).query).get("url") or [""])[0]
                    try:
                        body, ctype = reader.proxy(url)
                    except Exception:  # noqa: BLE001
                        body = b"<p style='color:#ccc;font-family:sans-serif;padding:24px'>Couldn't load this page.</p>"
                        ctype = "text/html; charset=utf-8"
                    self._send(body, ctype)
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

            # ---- POST: refresh, generic save, generic actions -------------
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
                elif self.path == "/api/save":
                    data = self._read_json()
                    section = next(
                        (s for s in viewer._sections if s.id == data.get("id")), None
                    )
                    if section is None:
                        self._json({"ok": False, "error": "unknown section"}, 404)
                        return
                    _apply_values(viewer._config, section, data.get("values") or {})
                    if viewer._on_save:
                        viewer._on_save()
                    self._json({"ok": True})
                elif self.path == "/api/action":
                    data = self._read_json()
                    fn = viewer._actions.get(data.get("action"))
                    if fn is None:
                        self._json({"ok": False, "error": "unknown action"}, 404)
                        return
                    self._json(fn(data.get("payload") or {}))
                else:
                    self.send_response(404)
                    self.end_headers()

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        url = f"http://127.0.0.1:{self.port}"

        if open_window:
            threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

            # Preferred: the cross-platform native shell (real OS window + native
            # tabs). Falls back to pywebview, then to a plain browser tab.
            try:
                from . import native_shell

                native_shell.run(url)
                return
            except ImportError:
                pass

            try:
                import webview  # pywebview

                webview.create_window("skroli", url, width=1200, height=900)
                webview.start()
                return
            except ImportError:
                print("  (no native toolkit installed; open the URL below)")

            print(f"\n  skroli is running → open {url}\n  Ctrl-C to stop.\n")
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                print("\n  stopped.")
            return

        print(f"\n  skroli is running → open {url}\n  Ctrl-C to stop.\n")
        try:
            self._httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  stopped.")
