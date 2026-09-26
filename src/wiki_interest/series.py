"""Pageview time series: per-article views (redirects merged), edition totals, share.

Conventions
- Daily data are fetched in calendar-year chunks so completed years are cached
  permanently and a changed period ("use 3 years") reuses the cache.
- Only complete months enter the analysis window.
- share = topic views / edition total views * 1e6 ("views per million edition views").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from .api import PAGEVIEWS_START, WikimediaClient, today
from .errors import DataError

PERIOD_RE = re.compile(r"^\s*(\d+)\s*([my])\s*$", re.I)
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")
MAX_REDIRECTS = 50


# -- periods ------------------------------------------------------------------
@dataclass(frozen=True)
class Period:
    start: date  # first day of first month
    end: date  # last day of last month

    @property
    def months(self) -> int:
        return (self.end.year - self.start.year) * 12 + self.end.month - self.start.month + 1

    def to_dict(self) -> dict:
        return {
            "start": self.start.strftime("%Y-%m"),
            "end": self.end.strftime("%Y-%m"),
            "months": self.months,
        }


def month_end(d: date) -> date:
    nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return nxt - timedelta(days=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def _parse_month(value: str, field_name: str) -> date:
    m = MONTH_RE.match(value.strip())
    if not m:
        raise DataError(
            f"{field_name}='{value}' is not a month.", hint=f"Use YYYY-MM for {field_name}, e.g. 2024-01."
        )
    return date(int(m.group(1)), int(m.group(2)), 1)


def last_complete_month(now: date | None = None) -> date:
    now = now or today()
    return add_months(now.replace(day=1), -1)


def parse_period(
    period: str | None = "24m", start: str | None = None, end: str | None = None
) -> Period:
    """'24m' / '2y' back from the last complete month, or explicit YYYY-MM bounds."""
    last = last_complete_month()
    end_m = _parse_month(end, "end") if end else last
    if end_m > last:
        raise DataError(
            f"end={end_m:%Y-%m} is not a complete month yet (last complete: {last:%Y-%m}).",
            hint=f"Use --end {last:%Y-%m} or omit --end.",
        )
    if start:
        start_m = _parse_month(start, "start")
    else:
        m = PERIOD_RE.match(period or "24m")
        if not m:
            raise DataError(
                f"period='{period}' not understood.", hint="Use e.g. 24m, 36m, 2y, 5y."
            )
        n = int(m.group(1)) * (12 if m.group(2).lower() == "y" else 1)
        start_m = add_months(end_m, -(n - 1))
    if start_m < PAGEVIEWS_START:
        start_m = PAGEVIEWS_START  # data exist from 2015-07
    if start_m > end_m:
        raise DataError(
            f"start {start_m:%Y-%m} is after end {end_m:%Y-%m}.", hint="Swap or fix --start/--end."
        )
    return Period(start_m, month_end(end_m))


def year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Calendar-year request windows covering [start, end], clipped to available data."""
    latest = today() - timedelta(days=1)
    chunks = []
    for year in range(start.year, end.year + 1):
        a = max(date(year, 1, 1), PAGEVIEWS_START)
        b = min(date(year, 12, 31), latest)
        if a <= b:
            chunks.append((a, b))
    return chunks


# -- fetching -----------------------------------------------------------------
def _to_series(items: dict[str, int], start: date, end: date) -> pd.Series:
    idx = pd.date_range(start, end, freq="D")
    s = pd.Series(items, dtype="float64")
    if len(s):
        s.index = pd.to_datetime(s.index, format="%Y%m%d")
    return s.reindex(idx, fill_value=0.0)


def fetch_article_daily(
    client: WikimediaClient, domain: str, title: str, start: date, end: date
) -> pd.Series:
    items: dict[str, int] = {}
    for a, b in year_chunks(start, end):
        items.update(client.per_article(domain, title, a, b, "daily"))
    return _to_series(items, start, end)


def fetch_total_daily(client: WikimediaClient, domain: str, start: date, end: date) -> pd.Series:
    items: dict[str, int] = {}
    for a, b in year_chunks(start, end):
        items.update(client.aggregate(domain, a, b, "daily"))
    s = _to_series(items, start, end)
    if (s == 0).all():
        raise DataError(
            f"{domain} has no pageview data for this period.",
            hint="Check the language code; tiny or new editions may lack data.",
        )
    return s


def expand_redirects(
    client: WikimediaClient, domain: str, titles: list[str], max_redirects: int = MAX_REDIRECTS
) -> tuple[list[str], list[str], list[str]]:
    """Return (canonical titles, all titles to fetch incl. redirects, warnings)."""
    canonical, fetch, warnings = [], [], []
    for t in titles:
        canon, redirs = client.redirects(domain, t, limit=max_redirects)
        if canon not in canonical:
            canonical.append(canon)
        for x in [canon, *redirs]:
            if x not in fetch:
                fetch.append(x)
        if len(redirs) >= max_redirects:
            warnings.append(
                f"{domain}: '{canon}' has more than {max_redirects} redirects; only the first "
                f"{max_redirects} were merged."
            )
    return canonical, fetch, warnings


@dataclass
class TopicSeries:
    """Pageviews of one topic (a set of articles, summed) in one language edition."""

    topic: str  # topic label
    lang: str
    domain: str
    titles: list[str]  # canonical article titles
    fetched_titles: list[str]  # canonical + redirects
    period: Period
    daily_views: pd.Series
    daily_total: pd.Series
    warnings: list[str] = field(default_factory=list)

    @property
    def monthly_views(self) -> pd.Series:
        return self.daily_views.resample("MS").sum()

    @property
    def monthly_total(self) -> pd.Series:
        return self.daily_total.resample("MS").sum()

    @property
    def monthly_share(self) -> pd.Series:
        """Views per million views of the whole edition."""
        return self.monthly_views / self.monthly_total * 1e6

    def monthly_frame(self) -> pd.DataFrame:
        df = pd.DataFrame(
            {
                "views": self.monthly_views,
                "edition_total": self.monthly_total,
                "share_per_million": self.monthly_share,
            }
        )
        df.index.name = "month"
        return df

    def daily_frame(self) -> pd.DataFrame:
        df = pd.DataFrame({"views": self.daily_views, "edition_total": self.daily_total})
        df.index.name = "date"
        return df


def build_topic_series(
    client: WikimediaClient,
    topic: str,
    lang: str,
    domain: str,
    titles: list[str],
    period: Period,
    merge_redirects: bool = True,
) -> TopicSeries:
    if merge_redirects:
        canonical, fetch, warnings = expand_redirects(client, domain, titles)
    else:
        canonical, fetch, warnings = list(titles), list(titles), []
    views = sum(
        (fetch_article_daily(client, domain, t, period.start, period.end) for t in fetch),
        start=_to_series({}, period.start, period.end),
    )
    total = fetch_total_daily(client, domain, period.start, period.end)
    return TopicSeries(topic, lang, domain, canonical, fetch, period, views, total, warnings)


def indexed(series: pd.Series, base_months: int = 3) -> pd.Series:
    """Index a monthly series so the mean of the first ``base_months`` months = 100."""
    base = series.iloc[:base_months].mean()
    if not base or pd.isna(base):
        return series * float("nan")
    return series / base * 100.0


def first_active_month(monthly: pd.Series) -> pd.Timestamp | None:
    nz = monthly[monthly > 0]
    return None if nz.empty else nz.index[0]
