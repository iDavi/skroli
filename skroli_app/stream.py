"""Minimal WebSocket streaming, standard library only.

We only ever push server → client (a feed of items), so this is deliberately
tiny: just enough of RFC 6455 to do the handshake, send text frames, and notice
when a client disconnects. A ``Broadcaster`` fans one message out to everyone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import threading

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def accept_key(client_key: str) -> str:
    """Compute the Sec-WebSocket-Accept value for the handshake."""
    digest = hashlib.sha1((client_key + _WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def encode_text(text: str) -> bytes:
    """Frame a string as a single unmasked text frame (server → client)."""
    payload = text.encode("utf-8")
    n = len(payload)
    header = bytearray([0x81])  # FIN + opcode 0x1 (text)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + payload


def read_message(rfile) -> tuple[int | None, bytes]:
    """Read one client frame. Returns (opcode, payload); (None, b'') at EOF.

    Client frames are masked per spec; we unmask. We don't need the payload for
    anything (the client never sends data), but we must drain frames to detect
    a clean close (opcode 0x8).
    """
    head = rfile.read(2)
    if len(head) < 2:
        return None, b""
    opcode = head[0] & 0x0F
    masked = head[1] & 0x80
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", rfile.read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", rfile.read(8))[0]
    mask = rfile.read(4) if masked else b""
    data = rfile.read(length)
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data


class Client:
    """One connected WebSocket. ``send`` is thread-safe (the broadcaster and the
    per-connection thread can both write)."""

    def __init__(self, conn):
        self._conn = conn
        self._lock = threading.Lock()

    def send(self, text: str) -> None:
        with self._lock:
            self._conn.sendall(encode_text(text))


class Broadcaster:
    """Keeps the set of live clients and fans messages out to all of them."""

    def __init__(self):
        self._clients: set[Client] = set()
        self._lock = threading.Lock()

    def add(self, client: Client) -> None:
        with self._lock:
            self._clients.add(client)

    def remove(self, client: Client) -> None:
        with self._lock:
            self._clients.discard(client)

    def publish(self, message: dict) -> None:
        text = json.dumps(message)
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            try:
                client.send(text)
            except OSError:
                self.remove(client)
