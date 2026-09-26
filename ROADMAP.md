# Roadmap

How to extend wiki-interest. Each item notes where it plugs in.

## 1. Topic clusters via Wikidata and categories

Today a topic is one or more hand-picked entities. Next:
- `cluster` command: from a seed QID, collect related entities with SPARQL
  (`P279` subclass of, `P361` part of, `P31` instance of, "main subject" `P921`) and/or
  a Wikipedia category tree (depth-limited, per language), then let the user prune.
- Weighting: rank members by sitelinks and median views; drop members that dominate
  by volume but not by intent (e.g. a whole language article inside "learning English").
- Plugs into `spec.py` as `topics[].cluster: {seed: Q.., relations: [...], max: 30}`,
  resolved into `qids` + `articles` and saved into the run's spec for reproducibility.

## 2. Bulk pageview dumps + Parquet/DuckDB for large-scale scans

The REST API is fine for tens of articles, not for "scan all 60k health articles in
20 languages". Next:
- Ingest monthly `pageviews` / `pagecounts-ez` dumps (dumps.wikimedia.org) into
  partitioned Parquet (`project/month`), query with DuckDB.
- A `scan` command: top growing articles per edition/category with the same `stats.py`
  functions applied in batch (vectorised Theil–Sen over many series).
- Keep the API path for small interactive requests; the engine chooses the backend by
  series count.

## 3. Clickstream data

Wikimedia clickstream (monthly, for several editions) shows how readers arrive
(search, other articles, external) and where they go next.
- Adds "intent" signals: share of arrivals from search engines ≈ active information
  need; paths toward commercial topics (e.g. `IELTS` → `Language school`).
- New reference metrics per topic; available only for editions with clickstream dumps
  (report this explicitly, like missing articles).

## 4. Per-capita normalization by speaker population

Share of edition views compares attention inside an edition; founders also need size.
- Add a small bundled table of speakers/internet users per language (with source and
  year), and report "views per 100k internet users" alongside share.
- Must remain a separate, clearly labelled metric: speaker counts are uncertain, and an
  edition's readership is not its speaker population (e.g. many Ukrainians read `ru`/`en`).

## 5. Cross-validation with other sources

Increase trust by agreement:
- Google Trends (via an official or cached export), app-store category ranks, Reddit/
  YouTube counts, search-volume tools the user already has.
- A `validate` step that takes a CSV from another source and reports rank correlation
  and trend-direction agreement with our series; disagreement becomes a warning and
  can cap confidence.

## 6. Forecasting

- Seasonal naive + ETS/ARIMA (statsmodels) with prediction intervals, on log share.
- Backtesting (rolling origin) to report forecast error per edition; only show
  forecasts where backtest error is acceptable, otherwise say "not forecastable".
- Output as `forecast_12m_pct` with interval and a confidence label computed like the
  trend label.

## 7. Ranking languages/topics by user-defined criteria

Founders weigh growth, size and certainty differently.
- Spec field `ranking: {weights: {growth: 0.5, share: 0.3, volume: 0.2},
  min_confidence: moderate, exclude: [...]}`, computed deterministically in the engine.
- Report shows the ranking table with each component, so the model explains the
  ranking instead of inventing one.

## 8. Growing the eval set from real failures

- Every real conversation where the agent failed (wrong entity, invented number,
  missing caveat, started over instead of editing the spec) becomes a case in
  `tests/evals/prompts.yaml` with an automatic check where possible.
- Keep the fixed transcripts from `run_evals.py` for regression comparisons between
  skill versions and between models (Haiku vs larger models).
- Track pass rates per check over time; a drop blocks release of SKILL.md changes.
- Already added from the first smoke run: `python -m uv` fallback, "never cd into
  the skill dir", `needs_confirmation` for "learning English".
