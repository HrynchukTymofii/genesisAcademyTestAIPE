# Library API (last resort)

Use only when the CLI and a spec cannot express the request (e.g. a custom metric,
a different aggregation, a one-off calculation over saved series). Write a short
script and run it with:

```
uv run --project <skill_dir> python my_script.py
```

Never re-implement the statistics: call `assess`/`trend` and quote their output.

## Typical glue script

```python
from wiki_interest import (
    WikimediaClient, entity_info, parse_period, build_topic_series, assess, load_run,
)

client = WikimediaClient()                       # cached, polite, retries
period = parse_period("36m")                      # or parse_period(start="2022-01", end="2025-12")
ent = entity_info(client, ["Q333"], ["uk"])["Q333"]
ts = build_topic_series(client, ent.label, "uk", ent.domains["uk"], [ent.titles["uk"]], period)

# custom slice: only school months (Sep-Jun), then the standard statistics
mask = ~ts.daily_views.index.month.isin([7, 8])
result = assess(ts.daily_views[mask], ts.daily_total[mask], metric="share")
print({k: result[k] for k in ("verdict", "confidence", "trend", "reasons", "warnings")})
```

## Functions

| Name | Module | Purpose |
|---|---|---|
| `WikimediaClient()` | api | HTTP client with SQLite cache, retries, rate limit, User-Agent. |
| `resolve_topic(client, text, langs)` | resolve | Text → `{status, qid, titles, candidates…}`; status `resolved`, `needs_confirmation`, `ambiguous`, `not_found`. |
| `entity_info(client, qids, langs)` | resolve | QIDs → `Entity` (label, description, `titles[lang]`, `domains[lang]`, `available_langs`). |
| `parse_period(period, start, end)` | series | → `Period(start, end)`, complete months only. |
| `build_topic_series(client, topic, lang, domain, titles, period)` | series | → `TopicSeries` with `daily_views`, `daily_total`, `monthly_views`, `monthly_share`, redirects merged. |
| `indexed(monthly, base_months)` | series | Base-period mean = 100. |
| `assess(daily_views, daily_total, metric)` | stats | Full statistics + `confidence`, `reasons`, `warnings`. |
| `trend(monthly)` / `verdict(trend)` | stats | Theil–Sen %/yr, bootstrap CI, Mann–Kendall p / verdict word. |
| `year_over_year(monthly)` | stats | Last 12 vs previous 12 months, same-month comparisons. |
| `detect_spikes(daily)` | stats | Boolean mask of spike days. |
| `seasonality_strength(monthly)` | stats | STL strength (≥36 months) or `None`. |
| `validate_spec(dict)` / `load_spec(path, overrides)` | spec | Build an `AnalysisSpec`. |
| `run_analysis(spec)` | engine | Same as `run`; returns the compact summary and creates a run dir. |
| `load_run(run_dir)` | engine | Read `result.json` (compact results + full `details`). |
| `make_chart(run_dir, kind)` | charts | PNG path. |
| `build_report(run_dir, summary, lang)` | report | One-page PDF; enforces the number guard. |
| `check_summary_numbers(result, text)` | report | Numbers in `text` not present in results. |

## Saved series

`<run_dir>/series/<topic>_<lang>_monthly.csv` columns: `month, views, edition_total,
share_per_million`; `_daily.csv`: `date, views, edition_total`. Read with pandas for
custom tables; print only small summaries, never whole series.
