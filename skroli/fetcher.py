"""Shared HTTP fetching with per-domain rate limiting and retries.

Every outbound request goes through here so throttling and back-off are decided
*by domain*: two requests to the same host are serialized and spaced apart,
while different hosts proceed independently. One slow or rate-limited source
can't stall the others. Standard library only.
"""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

USER_AGENT = "skroli/0.0.1 (+https://github.com/iDavi/skroli)"
DEFAULT_GAP = 1.0       # min seconds between requests to the same domain
DEFAULT_RETRIES = 3
TIMEOUT = 20


class Fetcher:
    def __init__(self, gap: float = DEFAULT_GAP, retries: int = DEFAULT_RETRIES):
        self.gap = gap
        self.retries = retries
        self._registry = threading.Lock()
        self._domain_locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        # Per-domain overrides (e.g. Reddit wants a wider gap).
        self._gaps: dict[str, float] = {}

    def set_domain_gap(self, domain: str, gap: float) -> None:
        self._gaps[domain] = gap

    def _domain_lock(self, domain: str) -> threading.Lock:
        with self._registry:
            lock = self._domain_locks.get(domain)
            if lock is None:
                lock = self._domain_locks[domain] = threading.Lock()
            return lock

    def get(self, url: str, headers: dict | None = None) -> bytes:
        domain = urlparse(url).netloc
        gap = self._gaps.get(domain, self.gap)
        # Hold the domain lock for the whole request so same-domain calls never
        # overlap and always respect the spacing; other domains run in parallel.
        with self._domain_lock(domain):
            last = self._last.get(domain)
            if last is not None:
                wait = gap - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
            try:
                return self._request(url, headers)
            finally:
                self._last[domain] = time.monotonic()

    def _request(self, url: str, headers: dict | None) -> bytes:
        merged = {"User-Agent": USER_AGENT}
        if headers:
            merged.update(headers)
        req = urllib.request.Request(url, headers=merged)
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code != 429 or attempt == self.retries - 1:
                    raise
                retry_after = exc.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else 0.0
                except ValueError:
                    wait = 0.0
                wait = max(wait, 5.0 * (2 ** attempt))  # 5s, 10s, 20s…
                print(f"  · rate-limited (429), retrying in {wait:.0f}s…")
                time.sleep(wait)
        raise RuntimeError("unreachable")


# Process-wide shared instance so per-domain state is global across ingestors.
SHARED = Fetcher()
SHARED.set_domain_gap("www.reddit.com", 2.0)


def fetch(url: str, headers: dict | None = None) -> bytes:
    return SHARED.get(url, headers=headers)
