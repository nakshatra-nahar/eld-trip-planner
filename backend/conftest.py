"""Shared pytest fixtures for the backend: offline test doubles for upstream HTTP.

Fixtures: ``load_fixture`` (read a captured OSRM JSON), ``fake_response`` (build a
response) and ``fake_session`` (a session that replays queued responses/exceptions).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
import requests

FIXTURES = Path(__file__).parent / "trips" / "tests" / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES / name
    if name.endswith(".gz"):
        with gzip.open(path) as fh:
            raw = fh.read()
    else:
        raw = path.read_bytes()
    return json.loads(raw)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: Any = None, text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self._text = text

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Replays queued results (a FakeResponse or an exception) and records each call."""

    def __init__(self, *results: Any):
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict | None = None, timeout: float | None = None) -> FakeResponse:
        self.calls.append({"url": url, "params": params or {}, "timeout": timeout})
        if not self.results:
            raise AssertionError(f"unexpected request to {url}")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Throttle history lives in the cache; start every test with a clean slate."""
    from django.conf import settings

    if not settings.configured:  # pure-engine runs with ``-p no:django``
        yield
        return
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture(name="load_fixture")
def load_fixture_fixture():
    return load_fixture


@pytest.fixture
def fake_response():
    return FakeResponse


@pytest.fixture
def fake_session():
    return FakeSession
