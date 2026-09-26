"""Stats on synthetic series with known shape."""

import numpy as np
import pandas as pd
import pytest

from wiki_interest import stats

START = "2022-09-01"


def daily(months: int, level_fn, seed: int = 1, noise: bool = True) -> pd.Series:
    """Daily Poisson views whose mean at day t (in years) is level_fn(t)."""
    idx = pd.date_range(START, periods=1, freq="D")
    end = (pd.Timestamp(START) + pd.DateOffset(months=months)) - pd.Timedelta(days=1)
    idx = pd.date_range(START, end, freq="D")
    t = np.arange(len(idx)) / 365.25
    mean = np.array([level_fn(x) for x in t])
    rng = np.random.default_rng(seed)
    vals = rng.poisson(mean) if noise else mean
    return pd.Series(vals.astype(float), index=idx)


def const_total(views: pd.Series, per_day: float = 1e6) -> pd.Series:
    return pd.Series(per_day, index=views.index)


# -- building blocks ---------------------------------------------------------------
def test_theil_sen_exact_line():
    slope, intercept = stats.theil_sen(np.array([1.0, 3, 5, 7, 9]))
    assert slope == pytest.approx(2) and intercept == pytest.approx(1)


def test_mann_kendall():
    assert stats.mann_kendall(np.arange(24.0)) < 1e-6
    rng = np.random.default_rng(0)
    assert stats.mann_kendall(rng.normal(size=24)) > 0.05
    assert stats.mann_kendall([5.0] * 10) == 1.0


def test_trend_known_growth_rate():
    monthly = pd.Series(100 * 1.5 ** (np.arange(36) / 12))  # +50%/yr exactly
    t = stats.trend(monthly)
    assert t.pct_per_year == pytest.approx(50, abs=0.01)
    assert t.ci_low <= 50 <= t.ci_high
    assert t.method == "log-theil-sen"


def test_trend_is_deterministic():
    s = daily(24, lambda t: 200).resample("MS").sum()
    assert stats.trend(s) == stats.trend(s)


def test_yoy():
    m = pd.Series([100.0] * 12 + [120.0] * 12)
    y = stats.year_over_year(m)
    assert y["last12_vs_prev12_pct"] == pytest.approx(20)
    assert y["same_month_up"] == 12
    assert stats.year_over_year(m.iloc[:20]) is None


# -- known shapes ------------------------------------------------------------------
def test_flat_series_is_stable():
    v = daily(24, lambda t: 300)
    r = stats.assess(v, const_total(v))
    assert r["verdict"] == "stable"
    assert r["confidence"] in ("strong", "moderate")
    assert abs(r["trend"]["pct_per_year"]) < 5
    assert r["spikes"]["spike_days"] == 0


def test_linear_growth_detected():
    v = daily(24, lambda t: 200 * (1 + 0.5 * t))  # +100 views/day per year
    r = stats.assess(v, const_total(v))
    assert r["verdict"] == "growing"
    assert r["confidence"] == "strong"
    assert r["trend"]["ci_low"] > 0
    assert r["yoy"]["last12_vs_prev12_pct"] > 20
    assert not r["warnings"]


def test_single_spike_removed_and_trend_unchanged():
    v = daily(24, lambda t: 300)
    v.iloc[400] = 30000
    r = stats.assess(v, const_total(v))
    assert r["spikes"]["spike_days"] == 1
    assert r["spikes"]["top_spike_days"][0]["views"] == 30000
    assert r["verdict"] == "stable" and r["verdict_without_spikes"] == "stable"


def test_growth_driven_by_spikes_is_flagged():
    v = daily(24, lambda t: 300)
    months = v.index.to_period("M")
    late = sorted(set(months))[-10:]
    for m in late:  # 4 viral days per month in the last 10 months
        days = v.index[months == m][[3, 10, 17, 24]]
        v[days] = 12000
    r = stats.assess(v, const_total(v))
    assert r["spikes"]["spike_days"] == 40
    assert r["verdict"] == "growing"
    assert r["verdict_without_spikes"] == "stable"
    assert r["confidence"] == "weak"
    assert any(w.startswith("growth driven by spikes in") for w in r["warnings"])


def test_seasonal_series():
    v = daily(48, lambda t: 300 * (1 + 0.6 * np.sin(2 * np.pi * t)))
    r = stats.assess(v, const_total(v))
    assert r["seasonality_strength"] > 0.6
    assert any("seasonality" in w for w in r["warnings"])
    assert r["verdict"] in ("stable", "unclear")


def test_raw_up_share_flat_when_edition_grows():
    v = daily(24, lambda t: 300 * 1.4**t)
    total = pd.Series(1e6 * 1.4 ** (np.arange(len(v)) / 365.25), index=v.index)
    r = stats.assess(v, total, metric="share")
    assert r["verdict"] == "stable"
    assert r["verdict_raw_views"] == "growing"
    assert "raw views growing but share stable" in r["warnings"]
    assert any("edition total traffic growing" in w for w in r["warnings"])


def test_low_volume_caps_confidence():
    v = daily(24, lambda t: 2 * (1 + t))  # median ~4 views/day
    r = stats.assess(v, const_total(v))
    assert r["confidence"] == "weak"
    assert any(w.startswith("very low volume") for w in r["warnings"])
    m = daily(24, lambda t: 15 * (1 + t))  # median ~30-ish: capped at moderate at most
    r2 = stats.assess(m, const_total(m))
    assert r2["confidence"] in ("moderate", "strong")
    if r2["median_daily_views"] < stats.VOLUME_MODERATE:
        assert r2["confidence"] == "moderate"


def test_insufficient_data_short_series():
    v = daily(8, lambda t: 300)
    r = stats.assess(v, const_total(v))
    assert r["confidence"] == "insufficient_data"
    assert "only 8 months" in r["reasons"][0]


def test_article_created_mid_period_is_trimmed():
    v = daily(24, lambda t: 0 if t < 0.5 else 300)
    r = stats.assess(v, const_total(v))
    assert r["data_from"] == "2023-03"
    assert r["months"] == 18
    assert r["confidence"] in ("moderate", "weak")
    assert any("no pageviews before 2023-03" in w for w in r["warnings"])
