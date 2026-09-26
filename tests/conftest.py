"""Shared fixtures. Tests never touch the network: HTTP is replayed from
tests/fixtures/http/*.json (recorded with tests/fixtures/record_fixtures.py)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from wiki_interest.api import WikimediaClient
from wiki_interest.cache import Cache

HTTP_DIR = Path(__file__).parent / "fixtures" / "http"
FIXED_TODAY = "2026-09-26"  # date the fixtures were recorded


def _load_recordings() -> dict[str, tuple[int, str]]:
    out = {}
    for f in HTTP_DIR.glob("*.json"):
        rec = json.loads(f.read_text(encoding="utf-8"))
        out[rec["url"]] = (rec["status"], rec["body"])
    return out


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolated cache, fixed 'today', temp working dir for run outputs."""
    monkeypatch.setenv("WIKI_INTEREST_TODAY", FIXED_TODAY)
    monkeypatch.setenv("WIKI_INTEREST_CACHE", str(tmp_path / "cache.sqlite"))
    monkeypatch.delenv("WIKI_INTEREST_RECORD_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def recorded(env):
    """Replay recorded Wikimedia responses; unknown URLs fail loudly."""
    data = _load_recordings()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in data:
            raise AssertionError(f"Unrecorded URL (re-run record_fixtures.py): {url}")
        status, body = data[url]
        return httpx.Response(status, text=body)

    with respx.mock(assert_all_called=False) as router:
        router.route().mock(side_effect=handler)
        yield router


@pytest.fixture
def client(recorded):
    c = WikimediaClient(cache=Cache(":memory:"), min_interval=0, backoff=0)
    yield c
    c.close()
