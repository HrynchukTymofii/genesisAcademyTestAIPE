"""Cross-check wiki-interest numbers against the Wikimedia monthly endpoint
(the data behind pageviews.wmcloud.org). Needs network; not part of pytest.

    uv run python tests/evals/cross_check.py

For each case it prints our monthly numbers next to the independent monthly-endpoint
numbers plus a pageviews.wmcloud.org link for a visual check.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import quote

import httpx

from wiki_interest.api import REST_BASE, encode_title, ssl_context, user_agent
from wiki_interest.api import WikimediaClient
from wiki_interest.series import Period, build_topic_series

PERIOD = Period(date(2025, 1, 1), date(2026, 8, 31))
CASES = [  # (lang, titles as given, merge_redirects)
    ("pl", ["Astronomia"], False),
    ("cs", ["Přerušovaný půst"], True),
    ("uk", ["Астрономія"], True),
]


def monthly_endpoint(http: httpx.Client, url: str) -> dict[str, int]:
    r = http.get(url)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return {it["timestamp"][:6]: it["views"] for it in r.json()["items"]}


def main() -> None:
    client = WikimediaClient()
    http = httpx.Client(headers={"User-Agent": user_agent()}, verify=ssl_context(), timeout=30)
    rng = f"{PERIOD.start:%Y%m%d}00/{PERIOD.end:%Y%m%d}00"
    worst_article, worst_total_pct = 0, 0.0
    for lang, titles, merge in CASES:
        domain = f"{lang}.wikipedia.org"
        ts = build_topic_series(client, "x", lang, domain, titles, PERIOD, merge_redirects=merge)
        ours = {k.strftime("%Y%m"): int(v) for k, v in ts.monthly_views.items()}
        ref: dict[str, int] = {}
        for t in ts.fetched_titles:  # same article + redirect set, independent requests
            url = f"{REST_BASE}/metrics/pageviews/per-article/{domain}/all-access/user/{encode_title(t)}/monthly/{rng}"
            for m, v in monthly_endpoint(http, url).items():
                ref[m] = ref.get(m, 0) + v
        diffs = [abs(ours.get(m, 0) - ref.get(m, 0)) for m in ours]
        tot_url = f"{REST_BASE}/metrics/pageviews/aggregate/{domain}/all-access/user/monthly/{rng}"
        ref_tot = monthly_endpoint(http, tot_url)
        our_tot = {k.strftime("%Y%m"): int(v) for k, v in ts.monthly_total.items()}
        tot_rel = [abs(our_tot[m] - ref_tot[m]) / ref_tot[m] * 100 for m in our_tot]
        worst_article = max(worst_article, *diffs)
        worst_total_pct = max(worst_total_pct, *tot_rel)
        last = max(ours)
        print(
            f"{lang} {titles} (+{len(ts.fetched_titles) - len(ts.titles)} redirects): "
            f"months={len(ours)} max|diff| views={max(diffs)}, edition totals {max(tot_rel):.3f}%; "
            f"{last}: ours={ours[last]} ref={ref.get(last)}; "
            f"total {last}: ours={our_tot[last]} ref={ref_tot.get(last)}"
        )
        page = "|".join(ts.fetched_titles)
        print(
            f"   https://pageviews.wmcloud.org/?project={domain}&platform=all-access&agent=user"
            f"&start={PERIOD.start}&end={PERIOD.end}&pages={quote(page)}"
        )
    # Article views must match exactly. Edition totals: Wikimedia's daily and monthly
    # aggregate endpoints differ slightly in a few reprocessed months (e.g. 2025-03,
    # 2026-04, <0.3%); we use daily sums consistently.
    ok = worst_article == 0 and worst_total_pct < 0.5
    print(
        ("PASS" if ok else "FAIL")
        + f": article views max diff {worst_article}, edition totals max diff {worst_total_pct:.3f}%"
    )


if __name__ == "__main__":
    main()
