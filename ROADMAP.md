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

## 7. Richer user-defined criteria (the basic version is built)

`--rank-by growth=..,share=..,volume=..,certainty=..` with `--min-confidence` already
ranks series by the user's own weights, explained per criterion. Next:
- More criteria: seasonality (prefer stable demand), recent momentum (last 6 months vs
  the trend), per-capita size (item 4), cross-source agreement (item 5).
- Hard constraints next to weights ("only editions with ≥ 50 views/day", "exclude en").
- Sensitivity check: report whether the top pick changes when weights move ±10 points,
  so the user sees how robust the recommendation is.

## 8. Derived comparisons ("contrasts")

Questions like "is the Ukraine–USA gap bigger than the Germany–Czech gap?" need numbers
that no single series has. Today the model would have to subtract trends itself, which
SKILL.md forbids and the report guard rejects. Plan:
- Spec field `contrasts: [{name, a: uk, b: en}, {name, a: de, b: cs}]` and
  `compare_contrasts: true`.
- Per contrast: gap in growth (points/yr) with a bootstrap CI computed from the paired
  series, and the share ratio. Across contrasts: difference of the gaps with its own CI
  and a confidence label using the same rules as trends.
- Chart of the gaps; numbers in the JSON so the model can quote them.

## 9. A sandboxed "custom analysis" tool

Some requests will always fall outside fixed commands (a new chart type, an unusual
metric). The model should then write a short script, and the system should run it
safely:
- **Narrow interface:** the script receives the run's series as DataFrames plus helper
  functions (trend, index, chart style) and returns declared outputs only: files
  (PNG/CSV) and a small dict of named numbers. Those numbers are saved in `result.json`
  as `custom` results, so the report guard accepts them and reviewers see their origin.
- **Isolation is the security boundary:** run in a container or micro-VM with no network,
  a read-only filesystem except a scratch dir, a non-root user, and CPU/memory/time
  limits (Docker `--network none --read-only`, gVisor/Firecracker, or a hosted sandbox).
  WebAssembly Python (Pyodide) is another option with no host access at all.
- **Defence in depth, not the boundary:** static checks (block `subprocess`, `socket`,
  file access outside scratch) for fast feedback to the model; a clean environment with
  no secrets; size limits on outputs; outputs treated as data, never as instructions
  (prompt-injection risk); the code logged next to the run for audit.
- Evals: prompts that need custom code, plus adversarial prompts that try to read files
  or reach the network, which must fail safely.

## 10. Growing the eval set from real failures

- Every real conversation where the agent failed (wrong entity, invented number,
  missing caveat, started over instead of editing the spec) becomes a case in
  `tests/evals/prompts.yaml` with an automatic check where possible.
- Keep the fixed transcripts from `run_evals.py` for regression comparisons between
  skill versions and between models (Haiku vs larger models).
- Track pass rates per check over time; a drop blocks release of SKILL.md changes.
- Already added from the first smoke run: `python -m uv` fallback, "never cd into
  the skill dir", `needs_confirmation` for "learning English".
- Later runs added: enforced confirmation after ambiguous topics (with an audited quote),
  tool-computed rankings and comparisons, `--min-daily-views`, source citations, and a
  skill description that triggers for "what did we find earlier?".

## 11. Separating "moved to AI" from "lost interest"

Share of edition views removes the edition-wide decline, but AI assistants replace some
topics faster than others (factual and school-type lookups more than news or culture).
Plan: benchmark each topic against a **peer basket** of similar articles (e.g. astronomy
vs other sciences in the same language, chosen via Wikidata classes or categories).
- Report the topic's trend *relative to its peers* next to the share trend.
- Falling like its peers → mostly a channel shift; falling faster → a real relative loss.
- Mark the ChatGPT launch (late 2022) as a structural break: compare before vs after
  instead of fitting one line across it.

## 12. Live verification of chat answers

The number check runs live for PDFs and in evals for chat answers. Next: run the same
checker on every chat answer as it is produced (e.g. a Claude Code hook after each
response) and ask the model to correct any unsupported number before the user sees it.
Also check that each number is attached to the right series (topic, language), not only
that it exists in the results.

## 13. Meaning-based search in history

`history` searches by keywords, topic, language and QID, which is enough for hundreds of
runs. For larger histories, add embeddings of each run's request and headline with a
vector index, combined with the keyword search (hybrid retrieval), so "that diet thing"
finds "intermittent fasting".
