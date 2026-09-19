"""Shared HTTP plumbing for the free upstream services (OSRM, Photon, Nominatim)."""

from __future__ import annotations

import threading
import time

import requests

USER_AGENT = "eld-trip-planner/1.0 (+https://github.com/; Spotter AI assessment)"

_local = threading.local()


def session() -> requests.Session:
    """A per-thread keep-alive session (requests.Session is not thread-safe)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        _local.session = s
    return s


class Deadline:
    """A wall-clock budget shared by every upstream call made for one request."""

    def __init__(self, seconds: float | None):
        self._end = None if seconds is None else time.monotonic() + seconds

    def remaining(self) -> float | None:
        return None if self._end is None else max(0.0, self._end - time.monotonic())

    def timeout(self, default: float, minimum: float = 1.0) -> float:
        """Per-call timeout: ``default`` capped by the remaining budget (never below ``minimum``)."""
        rem = self.remaining()
        return default if rem is None else max(minimum, min(default, rem))

    @property
    def expired(self) -> bool:
        rem = self.remaining()
        return rem is not None and rem <= 0.0
