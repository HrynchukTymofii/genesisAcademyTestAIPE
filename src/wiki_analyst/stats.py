"""Deterministic trend statistics and the confidence label.

All numbers an agent may quote are computed here. See references/methodology.md.

Trend: Theil–Sen slope on log(monthly value) -> % per year (linear fallback when
zeros exist), 95% CI from a circular moving-block bootstrap of residuals (seeded),
Mann–Kendall p-value. Spikes: days > rolling median + k * MAD (scaled).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

LEVELS = ["insufficient_data", "weak", "moderate", "strong"]

# thresholds (documented in references/methodology.md)
P_STRONG = 0.01
P_SIG = 0.05
STABLE_BAND = 10.0  # %/yr: CI inside +-10 => "stable"
STABLE_STRONG_BAND = 5.0
MIN_MONTHS = 12
FULL_MONTHS = 24
SEASONAL_MONTHS = 36
VOLUME_WEAK = 5  # median daily views below this caps confidence at weak
VOLUME_MODERATE = 30  # below this caps at moderate
EDITION_DRIFT = 10.0  # %/yr change of the whole edition worth a warning
SPIKE_K = 5.0
SPIKE_WINDOW = 31
SPIKE_MIN_EXCESS = 10  # a spike must exceed the rolling median by >= 10 views


# -- trend ----------------------------------------------------------------------
@dataclass
class Trend:
    pct_per_year: float | None
    ci_low: float | None
    ci_high: float | None
    mk_p: float | None
    method: str
    n_months: int

    def to_dict(self) -> dict:
        return asdict(self)


def _pairs(n: int) -> tuple[np.ndarray, np.ndarray]:
    i, j = np.triu_indices(n, k=1)
    return i, j


def theil_sen(y: np.ndarray) -> tuple[float, float]:
    """(slope per step, intercept) — median of pairwise slopes."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    i, j = _pairs(n)
    slope = float(np.median((y[j] - y[i]) / (j - i)))
    intercept = float(np.median(y - slope * np.arange(n)))
    return slope, intercept


def _theil_sen_many(Y: np.ndarray) -> np.ndarray:
    n = Y.shape[1]
    i, j = _pairs(n)
    return np.median((Y[:, j] - Y[:, i]) / (j - i), axis=1)


def mann_kendall(y) -> float | None:
    """Two-sided Mann–Kendall p-value with tie correction."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 4:
        return None
    i, j = _pairs(n)
    s = float(np.sign(y[j] - y[i]).sum())
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    if var <= 0:
        return 1.0
    z = (s - np.sign(s)) / math.sqrt(var) if s != 0 else 0.0
    return float(2 * (1 - norm.cdf(abs(z))))


def _to_pct(slope: float, log: bool, level: float) -> float:
    if log:
        return (math.exp(12 * slope) - 1) * 100
    return slope * 12 / level * 100 if level else float("nan")


def trend(monthly: pd.Series, n_boot: int = 1000, seed: int = 0) -> Trend:
    """Growth rate in % per year with bootstrap 95% CI and Mann–Kendall p."""
    y = np.asarray(monthly.dropna(), dtype=float)
    n = len(y)
    if n < 6 or not np.any(y > 0):
        return Trend(None, None, None, None, "insufficient", n)
    log = bool(np.all(y > 0))
    z = np.log(y) if log else y
    level = float(np.mean(y))
    slope, intercept = theil_sen(z)
    pct = _to_pct(slope, log, level)
    lo = hi = None
    if n_boot:
        fitted = intercept + slope * np.arange(n)
        resid = z - fitted
        block = max(3, int(round(n ** (1 / 3))))
        rng = np.random.default_rng(seed)
        n_blocks = math.ceil(n / block)
        starts = rng.integers(0, n, size=(n_boot, n_blocks))
        idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n  # circular blocks
        idx = idx.reshape(n_boot, -1)[:, :n]
        slopes = _theil_sen_many(fitted[None, :] + resid[idx])
        lo_s, hi_s = np.percentile(slopes, [2.5, 97.5])
        lo, hi = _to_pct(float(lo_s), log, level), _to_pct(float(hi_s), log, level)
    return Trend(pct, lo, hi, mann_kendall(z), "log-theil-sen" if log else "linear-theil-sen", n)


def verdict(t: Trend) -> str:
    if t.pct_per_year is None:
        return "unknown"
    sig = t.mk_p is not None and t.mk_p < P_SIG
    if t.ci_low is not None and sig and t.ci_low > 0:
        return "growing"
    if t.ci_high is not None and sig and t.ci_high < 0:
        return "declining"
    if t.ci_low is not None and t.ci_low > -STABLE_BAND and t.ci_high < STABLE_BAND:
        return "stable"
    if t.ci_low is None:  # no CI: fall back to p-value only
        if sig:
            return "growing" if t.pct_per_year > 0 else "declining"
        return "stable" if abs(t.pct_per_year) < STABLE_BAND else "unclear"
    return "unclear"


# -- year over year -------------------------------------------------------------
def year_over_year(monthly: pd.Series) -> dict | None:
    """Last 12 months vs previous 12 (mean level), plus same-month comparisons."""
    y = monthly.dropna()
    if len(y) < 24:
        return None
    last, prev = y.iloc[-12:], y.iloc[-24:-12]
    pct = (last.mean() / prev.mean() - 1) * 100 if prev.mean() > 0 else None
    same = []
    for a, b in zip(prev.values, last.values):
        if a > 0:
            same.append((b / a - 1) * 100)
    return {
        "last12_vs_prev12_pct": pct,
        "same_month_up": int(sum(1 for x in same if x > 0)),
        "same_month_compared": len(same),
        "same_month_median_pct": float(np.median(same)) if same else None,
    }


# -- spikes -----------------------------------------------------------------------
def detect_spikes(daily: pd.Series, k: float = SPIKE_K, window: int = SPIKE_WINDOW) -> pd.Series:
    """Boolean mask of spike days: views > rolling median + k * 1.4826 * rolling MAD,
    and at least 2x the median and +SPIKE_MIN_EXCESS views."""
    med = daily.rolling(window, center=True, min_periods=7).median()
    mad = (daily - med).abs().rolling(window, center=True, min_periods=7).median() * 1.4826
    thresh = med + k * mad
    return (daily > thresh) & (daily > 2 * med) & (daily - med >= SPIKE_MIN_EXCESS)


def remove_spikes(daily: pd.Series, mask: pd.Series, window: int = SPIKE_WINDOW) -> pd.Series:
    med = daily.rolling(window, center=True, min_periods=7).median()
    return daily.where(~mask, med)


def spike_summary(daily: pd.Series, mask: pd.Series, top: int = 3) -> dict:
    excess = (daily - remove_spikes(daily, mask)).where(mask, 0.0)
    by_month = excess.resample("MS").sum()
    top_months = [m.strftime("%Y-%m") for m in by_month[by_month > 0].nlargest(top).index]
    top_days = [
        {"date": d.strftime("%Y-%m-%d"), "views": int(daily[d])}
        for d in daily[mask].nlargest(top).index
    ]
    total = daily.sum()
    return {
        "spike_days": int(mask.sum()),
        "spike_share_of_views_pct": float(excess.sum() / total * 100) if total else 0.0,
        "top_spike_months": top_months,
        "top_spike_days": top_days,
    }


# -- seasonality -----------------------------------------------------------------
def seasonality_strength(monthly: pd.Series) -> float | None:
    """STL seasonal strength F_s = max(0, 1 - Var(R)/Var(S+R)); needs >= 36 months."""
    y = monthly.dropna()
    if len(y) < SEASONAL_MONTHS:
        return None
    from statsmodels.tsa.seasonal import STL

    z = np.log(y) if (y > 0).all() else y
    res = STL(z, period=12, robust=True).fit()
    denom = np.var(res.seasonal + res.resid)
    if denom == 0:
        return 0.0
    return float(max(0.0, 1 - np.var(res.resid) / denom))


# -- confidence ------------------------------------------------------------------
def _cap(level: str, cap: str) -> str:
    return LEVELS[min(LEVELS.index(level), LEVELS.index(cap))]


def _down(level: str) -> str:
    i = LEVELS.index(level)
    return LEVELS[max(1, i - 1)] if i > 0 else level


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:+.1f}%"


def assess(
    daily_views: pd.Series,
    daily_total: pd.Series,
    metric: str = "share",
    spike_k: float = SPIKE_K,
    n_boot: int = 1000,
    seed: int = 0,
) -> dict:
    """Full statistics + confidence label for one topic in one edition.

    ``daily_views``/``daily_total`` cover complete months only.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    # Trim leading months without any views (article created during the period).
    monthly_raw_all = daily_views.resample("MS").sum()
    active = monthly_raw_all[monthly_raw_all > 0]
    trimmed_from = None
    if not active.empty and active.index[0] > monthly_raw_all.index[0]:
        trimmed_from = active.index[0]
        warnings.append(
            f"no pageviews before {trimmed_from:%Y-%m} (article created or renamed then); "
            f"statistics use {trimmed_from:%Y-%m} onward"
        )
        daily_views = daily_views[daily_views.index >= trimmed_from]
        daily_total = daily_total[daily_total.index >= trimmed_from]

    mask = detect_spikes(daily_views, k=spike_k)
    clean_daily = remove_spikes(daily_views, mask)
    m_raw = daily_views.resample("MS").sum()
    m_total = daily_total.resample("MS").sum()
    m_share = m_raw / m_total * 1e6
    m_clean_raw = clean_daily.resample("MS").sum()
    m_clean_share = m_clean_raw / m_total * 1e6
    m_metric = m_share if metric == "share" else m_raw
    m_metric_clean = m_clean_share if metric == "share" else m_clean_raw
    n = int(m_metric.notna().sum())
    median_daily = float(daily_views.median()) if len(daily_views) else 0.0

    t_main = trend(m_metric, n_boot=n_boot, seed=seed)
    t_clean = trend(m_metric_clean, n_boot=n_boot, seed=seed)
    t_other = trend(m_raw if metric == "share" else m_share, n_boot=n_boot, seed=seed)
    t_total = trend(m_total, n_boot=0)
    v_main, v_clean, v_other = verdict(t_main), verdict(t_clean), verdict(t_other)
    yoy = year_over_year(m_metric)
    season = seasonality_strength(m_metric)
    spikes = spike_summary(daily_views, mask)

    out = {
        "metric": metric,
        "months": n,
        "verdict": v_main,
        "trend": t_main.to_dict(),
        "trend_without_spikes": t_clean.to_dict(),
        "verdict_without_spikes": v_clean,
        "trend_raw_views" if metric == "share" else "trend_share": t_other.to_dict(),
        "verdict_raw_views" if metric == "share" else "verdict_share": v_other,
        "edition_total_trend_pct_per_year": t_total.pct_per_year,
        "yoy": yoy,
        "seasonality_strength": season,
        "spikes": spikes,
        "median_daily_views": median_daily,
        "total_views": float(daily_views.sum()),
        "mean_share_per_million": float(m_share.mean()) if n else None,
        "last12_share_per_million": float(m_share.iloc[-12:].mean()) if n else None,
        "data_from": trimmed_from.strftime("%Y-%m") if trimmed_from is not None else None,
    }

    # insufficient data
    if n < MIN_MONTHS or median_daily < 1 or v_main == "unknown":
        why = (
            f"only {n} months of data (need {MIN_MONTHS})"
            if n < MIN_MONTHS
            else f"median {median_daily:.1f} views/day is too low to measure"
        )
        reasons.append(why)
        out.update(confidence="insufficient_data", reasons=reasons, warnings=warnings)
        return out

    # base level from the statistical evidence
    ci = f"95% CI {_fmt_pct(t_main.ci_low)}..{_fmt_pct(t_main.ci_high)}/yr"
    if v_main in ("growing", "declining"):
        level = "strong" if (t_main.mk_p or 1) < P_STRONG and n >= FULL_MONTHS else "moderate"
        reasons.append(
            f"{metric} {v_main} {_fmt_pct(t_main.pct_per_year)}/yr, {ci} excludes 0, "
            f"Mann-Kendall p={t_main.mk_p:.3g}"
        )
    elif v_main == "stable":
        strong_band = t_main.ci_low > -STABLE_STRONG_BAND and t_main.ci_high < STABLE_STRONG_BAND
        level = "strong" if strong_band and n >= FULL_MONTHS else "moderate"
        reasons.append(f"{metric} stable: {ci} lies within +-{STABLE_BAND:.0f}%/yr")
    else:
        level = "weak"
        reasons.append(
            f"no clear trend: {ci} is wide, Mann-Kendall p={t_main.mk_p:.3g}"
        )
    reasons.append(f"{n} complete months analysed")

    # caps and downgrades
    if n < FULL_MONTHS:
        level = _cap(level, "moderate")
        reasons.append(f"short series ({n} < {FULL_MONTHS} months) caps confidence at moderate")
    if median_daily < VOLUME_WEAK:
        level = _cap(level, "weak")
        warnings.append(f"very low volume (median {median_daily:.0f} views/day)")
    elif median_daily < VOLUME_MODERATE:
        level = _cap(level, "moderate")
        warnings.append(f"low volume (median {median_daily:.0f} views/day)")
    else:
        reasons.append(f"volume adequate (median {median_daily:.0f} views/day)")
    if trimmed_from is not None:
        level = _cap(level, "moderate")

    if v_clean != v_main:
        months = ", ".join(spikes["top_spike_months"]) or "the period"
        driver = {"growing": "growth", "declining": "decline"}.get(v_main, f"'{v_main}' verdict")
        warnings.append(
            f"{driver} driven by spikes in {months}; without spikes the trend is {v_clean} "
            f"({_fmt_pct(t_clean.pct_per_year)}/yr)"
        )
        level = _cap(level, "weak")
    elif spikes["spike_days"]:
        reasons.append(
            f"{spikes['spike_days']} spike days detected; verdict unchanged without them"
        )

    other_name = "raw views" if metric == "share" else "share"
    if v_other != v_main and {v_main, v_other} & {"growing", "declining"}:
        if metric == "share":
            warnings.append(f"raw views {v_other} but share {v_main}")
        else:
            warnings.append(f"raw views {v_main} but share {v_other}")
        level = _down(level)
    else:
        reasons.append(f"{other_name} agree ({v_other})")

    if t_total.pct_per_year is not None and abs(t_total.pct_per_year) >= EDITION_DRIFT:
        direction = "declining" if t_total.pct_per_year < 0 else "growing"
        warnings.append(
            f"edition total traffic {direction} {_fmt_pct(t_total.pct_per_year)}/yr"
            + ("; share corrects for this" if metric == "share" else "; raw views are distorted by it")
        )

    if yoy and yoy["last12_vs_prev12_pct"] is not None:
        y = yoy["last12_vs_prev12_pct"]
        if (v_main == "growing" and y < 0) or (v_main == "declining" and y > 0):
            warnings.append(f"year-over-year change ({_fmt_pct(y)}) contradicts the {v_main} trend")
            level = _down(level)
    elif yoy is None:
        reasons.append("year-over-year not computed (<24 months)")

    if season is not None and season >= 0.6:
        warnings.append(
            f"strong seasonality (strength {season:.2f}); compare same months across years"
        )
    elif season is None:
        reasons.append("seasonality not assessed (<36 months)")

    out.update(confidence=level, reasons=reasons, warnings=warnings)
    return out
