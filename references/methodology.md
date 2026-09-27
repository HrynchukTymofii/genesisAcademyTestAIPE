# Methodology

All statistics are computed in `src/wiki_analyst/stats.py`; they are deterministic
(bootstrap is seeded) and unit-tested on synthetic series.

## Data

- **Source:** Wikimedia REST Pageviews API, `agent=user` (identified bots and spiders
  excluded), `access=all-access`, daily granularity. Data exist from 2015-07-01.
- **Articles:** a topic is one or more Wikidata entities (and/or explicit titles); per
  language the article titles come from Wikidata sitelinks.
- **Redirects** (MediaWiki `prop=redirects`, namespace 0, up to 50) are fetched and
  their views **summed** into the article, so a rename does not create fake growth or
  decline. Several articles in one topic are summed the same way.
- **Edition totals** come from `/metrics/pageviews/aggregate/<lang>.wikipedia.org`.
- **Share** = topic views ÷ edition views × 10⁶ ("views per million edition views").
  Verdicts use share by default because whole editions gain/lose traffic (mobile apps,
  search engine answer boxes, AI summaries, platform changes); raw views are reported
  alongside.
- **Window:** complete months only; `end` defaults to the last complete month.
  If an article has no views at the start of the window (created later), leading empty
  months are trimmed and a warning is added.
- **Caching:** SQLite, keyed by URL. Requests are made in calendar-year chunks; chunks
  that end before the current month (and after the 3rd day of the month) are cached
  permanently, the current year for 6 hours; Wikidata/redirect lookups for 7 days.

## Trend

- Monthly series `y` (share or raw). If all `y > 0`: Theil–Sen slope `b` on `log y`
  (per month), **% per year = (e^{12b} − 1) × 100**. With zeros: linear Theil–Sen
  slope × 12 ÷ mean(y) × 100.
- **95% CI:** circular moving-block bootstrap of residuals around the Theil–Sen fit
  (block length max(3, round(n^{1/3})), 1000 resamples, seed 0), percentile interval.
- **Mann–Kendall** two-sided p-value with tie correction (no autocorrelation
  correction; the block-bootstrap CI covers serial dependence).
- **Verdict:** `growing`/`declining` if MK p < 0.05 and the CI excludes 0;
  `stable` if the whole CI lies within ±10 %/yr; otherwise `unclear`.
- The same trend is computed for raw views (or share, when metric=raw), for the series
  with spikes removed, and (without CI) for the edition total.

## Year over year

Mean of the last 12 months vs the previous 12 (`yoy_pct`), and the 12 same-month pairs
(`same_months_up` = months where the latest year is higher). Needs ≥ 24 months.

## Spikes

Daily views, rolling centred 31-day median `m` and MAD (×1.4826). A spike day has
views > m + k·MAD (k = 5), views > 2m, and views − m ≥ 10. Spike days are replaced by
`m` and the trend is recomputed ("trend without spikes").

## Seasonality

With ≥ 36 months: STL (period 12, robust) on log values; strength
F = max(0, 1 − Var(R)/Var(S+R)). F ≥ 0.6 adds a warning.

## Index

For charts and `index_recent`: base = mean of the first 12 months (if ≥ 24 months,
otherwise first 3) = 100; `index_recent` = mean of the last 12 (or 3) months. Equal
window lengths keep it seasonality-neutral.

## Confidence label

1. `insufficient_data` if < 12 months, median < 1 view/day, or no trend computable.
2. Base level: growing/declining with MK p < 0.01 and ≥ 24 months → `strong`,
   otherwise `moderate`; stable with CI inside ±5 %/yr and ≥ 24 months → `strong`,
   otherwise `moderate`; unclear → `weak`.
3. Caps and downgrades:
   - < 24 months → at most `moderate`.
   - median daily views < 5 → at most `weak`; < 30 → at most `moderate`.
   - article created during the window → at most `moderate`.
   - verdict changes when spikes are removed → at most `weak`
     ("growth driven by spikes in YYYY-MM").
   - share and raw verdicts disagree with a growing/declining direction → one level down.
   - YoY sign contradicts the trend → one level down.
4. `reasons` explain the base level; `warnings` list every cap and caveat.

## Entity resolution

`wbsearchentities` in English and each requested language; candidates ranked by exact
label/alias match, then number of Wikipedia editions. Disambiguation pages removed.
`resolved` only if one exact match dominates (≥ 4× the editions of the next exact match
and ≥ 10) AND has ≥ 25 editions; a weakly-covered exact match is `needs_confirmation`
(e.g. "Learning English" is a VOA programme); otherwise `ambiguous`.

## Known limitations

- Pageviews measure attention on Wikipedia, not demand, intent or willingness to pay.
- Wikipedia's share of information seeking differs by country and is changing.
- Some automated traffic passes as `agent=user`; spikes partly catch it.
- Articles not linked in Wikidata are missed unless added as `articles`.
- A language edition ≠ a country (e.g. `es`, `en`, `ar`, `pt`).
- Topics are only as good as the chosen articles; broad articles (e.g. a whole
  language) mix intents.
