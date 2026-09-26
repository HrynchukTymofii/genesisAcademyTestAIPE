from datetime import date

import httpx
import pandas as pd
import pytest
import respx

from wiki_interest.api import WikimediaClient
from wiki_interest.cache import Cache
from wiki_interest.errors import DataError
from wiki_interest.series import (
    Period,
    build_topic_series,
    indexed,
    parse_period,
    year_chunks,
)


def test_parse_period_relative(env):
    p = parse_period("24m")
    assert (p.start, p.end, p.months) == (date(2024, 9, 1), date(2026, 8, 31), 24)
    assert parse_period("2y") == p


def test_parse_period_explicit_and_clamped(env):
    p = parse_period(start="2014-01", end="2016-12")
    assert p.start == date(2015, 7, 1) and p.end == date(2016, 12, 31)


def test_parse_period_rejects_incomplete_month(env):
    with pytest.raises(DataError) as exc:
        parse_period(end="2026-09")
    assert "2026-08" in exc.value.hint


def test_parse_period_bad_value(env):
    with pytest.raises(DataError):
        parse_period("two years")


def test_year_chunks_clip_to_yesterday(env):
    chunks = year_chunks(date(2024, 9, 1), date(2026, 8, 31))
    assert chunks[0] == (date(2024, 1, 1), date(2024, 12, 31))
    assert chunks[-1] == (date(2026, 1, 1), date(2026, 9, 25))


def _items(prefix, views):
    return {"items": [{"timestamp": f"{prefix}{d:02d}00", "views": v} for d, v in views.items()]}


@respx.mock
def test_redirects_are_summed_and_share_computed(env):
    respx.get(url__regex=r"https://xx\.wikipedia\.org/w/api\.php.*").mock(
        return_value=httpx.Response(
            200,
            json={"query": {"pages": [{"title": "New name", "redirects": [{"title": "Old name"}]}]}},
        )
    )
    respx.get(url__regex=r".*/per-article/.*/New_name/.*").mock(
        return_value=httpx.Response(200, json=_items("202601", {1: 10, 2: 10}))
    )
    respx.get(url__regex=r".*/per-article/.*/Old_name/.*").mock(
        return_value=httpx.Response(200, json=_items("202601", {1: 5, 31: 5}))
    )
    respx.get(url__regex=r".*/aggregate/.*").mock(
        return_value=httpx.Response(200, json=_items("202601", {d: 1000 for d in range(1, 32)}))
    )
    client = WikimediaClient(cache=Cache(":memory:"), min_interval=0)
    period = Period(date(2026, 1, 1), date(2026, 1, 31))
    ts = build_topic_series(client, "t", "xx", "xx.wikipedia.org", ["Old name"], period)
    assert ts.titles == ["New name"]
    assert ts.fetched_titles == ["New name", "Old name"]
    assert ts.daily_views.sum() == 30
    assert ts.monthly_share.iloc[0] == pytest.approx(30 / 31000 * 1e6)


def test_recorded_series_merges_redirects(client):
    period = parse_period("24m")
    ts = build_topic_series(client, "astronomy", "uk", "uk.wikipedia.org", ["Астрономія"], period)
    assert ts.titles == ["Астрономія"]
    assert len(ts.fetched_titles) > 1  # redirects merged
    assert len(ts.monthly_views) == 24
    df = ts.monthly_frame()
    assert (df["share_per_million"] == df["views"] / df["edition_total"] * 1e6).all()
    assert ts.daily_views.index.min() == pd.Timestamp("2024-09-01")


def test_indexed_base_100():
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    out = indexed(s, base_months=2)
    assert out.iloc[0] == pytest.approx(200 / 3)
    assert out.iloc[:2].mean() == pytest.approx(100)
