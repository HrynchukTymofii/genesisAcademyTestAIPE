from datetime import date

import httpx
import pytest
import respx

from wiki_interest.api import WikimediaClient, encode_title, pageview_ttl, user_agent
from wiki_interest.cache import Cache
from wiki_interest.errors import ApiError


def make_client():
    return WikimediaClient(cache=Cache(":memory:"), min_interval=0, backoff=0, max_retries=2)


def test_user_agent_has_contact():
    ua = user_agent()
    assert ua.startswith("wiki-interest/") and "(" in ua and "http" in ua


def test_encode_title():
    assert encode_title("AC/DC song") == "AC%2FDC_song"
    assert encode_title("Астрономія") == "%D0%90%D1%81%D1%82%D1%80%D0%BE%D0%BD%D0%BE%D0%BC%D1%96%D1%8F"


def test_ttl_permanent_for_completed_months():
    now = date(2026, 9, 26)
    assert pageview_ttl(date(2026, 8, 31), now) is None
    assert pageview_ttl(date(2026, 9, 25), now) is not None
    # first days of a month: last month's data may still be settling
    assert pageview_ttl(date(2026, 8, 31), date(2026, 9, 1)) is not None


def test_cache_expiry(tmp_path):
    c = Cache(tmp_path / "c.sqlite")
    c.set("u1", 200, "{}", ttl=None)
    c.set("u2", 200, "{}", ttl=-1)
    assert c.get("u1") == (200, "{}")
    assert c.get("u2") is None
    assert c.stats()["permanent"] == 1


@respx.mock
def test_retries_then_succeeds_and_caches():
    route = respx.get("https://example.org/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"a": 1})]
    )
    client = make_client()
    assert client.get_json("https://example.org/x") == {"a": 1}
    assert client.get_json("https://example.org/x") == {"a": 1}  # from cache
    assert route.call_count == 2
    assert client.cache_hits == 1
    assert route.calls[0].request.headers["User-Agent"] == user_agent()


@respx.mock
def test_gives_up_with_actionable_error():
    respx.get("https://example.org/y").mock(return_value=httpx.Response(500))
    with pytest.raises(ApiError) as exc:
        make_client().get_json("https://example.org/y")
    assert "retry" in exc.value.hint.lower()


@respx.mock
def test_404_returns_none_and_per_article_is_empty():
    respx.get(url__regex=r".*/per-article/.*").mock(return_value=httpx.Response(404, json={}))
    client = make_client()
    assert client.per_article("pl.wikipedia.org", "Nope", date(2025, 1, 1), date(2025, 1, 31)) == {}
