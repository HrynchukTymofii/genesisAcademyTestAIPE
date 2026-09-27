# wiki-interest

An Agent Skill (Claude Code format) that uses Wikipedia pageviews to help B2C founders
decide **which topics to develop and which language markets to launch in**. It fetches
data, computes trend statistics you can trust, draws charts and writes a one-page PDF
report.

**New here? Read [`docs/GUIDE.md`](docs/GUIDE.md)**: how it all works, the statistics
in plain language, how it was verified, weak points, and links (about 3 hours).

It is designed to be driven by a small, cheap model (Claude Haiku 4.5). The code does
all data work and statistics. The model only translates requests into commands, reads
compact JSON, and writes the prose.

```
wiki-interest resolve "astronomy" --langs uk
wiki-interest analyze --qid Q333 --langs uk --period 36m
→ astronomy [uk]: declining -47.1%/yr in share of edition views (95% CI -53.2..-41.4), confidence strong
```

## Setup

Requirements: Python 3.11+ (uv installs it if needed), [uv](https://docs.astral.sh/uv/), internet.

```bash
# install as a personal skill (or copy into <project>/.claude/skills/)
cp -r wiki-interest ~/.claude/skills/wiki-interest
uv run --project ~/.claude/skills/wiki-interest wiki-interest --help   # first run installs deps from uv.lock
```

The model runs every command as `uv run --project <skill_dir> wiki-interest <command>`
from the user's directory; results go to `./wiki-interest-runs/<id>/`.

Environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `WIKI_INTEREST_CONTACT` | repo URL | Contact info in the User-Agent (Wikimedia policy). Set to your email/URL. |
| `WIKI_INTEREST_CACHE` | `~/.cache/wiki-interest/cache.sqlite` | Response cache. |
| `WIKI_INTEREST_RUNS` | `./wiki-interest-runs` | Where run dirs are created. |
| `WIKI_INTEREST_TODAY` | today | Fix "today" (reproducible runs, tests). |

**Windows and corporate/antivirus TLS notes**
- If `uv sync` fails with `invalid peer certificate: UnknownIssuer`, set
  `UV_SYSTEM_CERTS=1` (a TLS-inspecting proxy or antivirus is in the way).
- Some antivirus products (e.g. Avast) set `SSLKEYLOGFILE` to a pipe, which crashes
  OpenSSL. The client builds its own SSL context (system store + certifi) without key
  logging, so this is handled.
- If `uv` was installed with `pip install --user uv` it may not be on PATH;
  `python -m uv` works too. SKILL.md tells the model to fall back to it.

## Commands

| Command | Purpose |
|---|---|
| `resolve "<topic>" --langs pl,cs` | Topic → Wikidata QID → article per language. Status `resolved`, `needs_confirmation`, `ambiguous` or `not_found`. |
| `analyze --qid Q.. [--qid ..] --langs .. --period 24m [--start --end] [--metric share\|raw] [--article lang:Title]` | One topic (entities/articles summed) across languages. |
| `compare --qids Q1,Q2 --langs .. --period 36m` | Several topics side by side. |
| `... --rank-by growth=0.6,share=0.4 [--min-confidence moderate]` | Rank by the user's own criteria (growth, share, volume, certainty); explained scores. |
| `... --min-daily-views 10` / `--note "<user request>"` | Ignore tiny series in rankings / store the request so the run can be found later. |
| `history "<keywords>"` / `history --run <run_dir>` | Find earlier analyses (also in a new session) and re-read their numbers. |
| `run <spec.yaml\|run_dir> [--set key=value]` | Composite requests and follow-ups from a YAML spec. |
| `chart <run_dir> --kind indexed\|share\|raw` | PNG chart. |
| `report <run_dir> --summary "…" --lang en\|uk\|pl\|cs` | One-page PDF. |

Every command prints **one compact JSON object** (key numbers, confidence label,
reasons, warnings, file paths, next steps), never raw time series. Errors are JSON too,
with a `next_step` a model can follow, e.g.
`"No pl article for Q1666254 (intermittent fasting). Available: en, de, fr, es, ru, …"`.

## Design

```
SKILL.md ──► the model: resolve → confirm → analyze/compare/run → read JSON → answer → chart/report
                  │
src/wiki_interest/
  cli.py      typer commands, JSON in/out, errors → JSON
  engine.py   runs a spec end to end, writes the run dir (result.json, spec.yaml, series/, charts/)
  spec.py     pydantic spec; errors name the exact field; --set overrides
  resolve.py  Wikidata search + sitelinks; ambiguity policy
  series.py   per-article daily views, redirect merging, edition totals, share, index
  stats.py    Theil–Sen + block bootstrap CI, Mann–Kendall, YoY, spikes, STL, confidence
  charts.py   matplotlib line charts
  report.py   reportlab one-page PDF + summary number guard
  api.py      httpx client: retries, backoff, rate limit, User-Agent, SQLite cache (cache.py)
```

Key decisions:
- **Share of edition traffic by default.** Whole Wikipedia editions gain and lose
  traffic (e.g. uk −23.9%/yr, cs −14.7%/yr over the last years), so raw views mislead.
  Verdicts use views per million edition views; raw views are reported alongside, and
  disagreements become warnings ("raw views growing but share stable").
- **Cross-language comparisons** use growth rates, share, or an index (base = 100),
  never raw counts. The index uses a 12-month base vs the last 12 months when there are
  ≥ 24 months, so seasonality (school year) does not distort it.
- **Redirects are merged** (summed), so renames do not create fake growth; a topic can
  be a set of articles (e.g. TOEFL + IELTS + ESL for "learning English").
- **Confidence is computed, not judged:** strong / moderate / weak / insufficient_data
  plus machine-generated reasons and warnings. The model must quote it
  (`references/methodology.md`).
- **The model cannot invent numbers in the report:** `--summary` is rejected if it has
  numbers that are not in the run's results.
- **Never silently pick an entity:** ambiguous topics return candidates; exact matches
  with < 25 Wikipedia editions need confirmation ("Learning English" is a VOA radio
  programme, not the concept).
- **Follow-ups edit the saved spec** (`run <run_dir> --set languages=pl,cs,sk`); the
  cache makes reruns nearly free (a repeated 6-language, 3-year run: 0 HTTP requests,
  121 cache hits).
- **Caching:** calendar-year request chunks; completed years cached permanently, the
  current year for 6 h, Wikidata lookups for 7 days.

## How it was tested

**Unit and integration tests** — `uv run pytest` (88 tests, no network; also run by GitHub Actions on Ubuntu and Windows):
- Statistics on synthetic series of known shape: flat, linear growth, flat + single
  spike, spikes that fake growth, seasonal, edition growth (raw up / share flat), low
  volume, short series, article created mid-period; exact Theil–Sen on a line with a
  known +50%/yr rate.
- API client: retries/backoff, 404 handling, caching, TTLs, User-Agent.
- Resolve, series, CLI, spec and report tests replay **real recorded API responses**
  (`tests/fixtures/http/`, re-recorded with `tests/fixtures/record_fixtures.py`) via respx.
- Report: one page with a very long summary, Cyrillic font embedded, number guard.

**Cross-check against pageviews.wmcloud.org data** — `uv run python tests/evals/cross_check.py`
compares our daily-summed monthly numbers with independent requests to the Wikimedia
monthly endpoint (what pageviews.wmcloud.org displays), 2025-01..2026-08
(run 2026-09-26):

| Case | Article views | Edition totals |
|---|---|---|
| pl `Astronomia` | exact match all 20 months (2026-08: 1 038) | max diff 0.25% |
| cs `Přerušovaný půst` | exact match (2026-08: 119) | max diff 0.29% |
| uk `Астрономія` + redirect `Astronomy` | exact match (2026-08: 362) | max diff 0.13% |

The small edition-total differences occur only in 2025-03 and 2026-04, in all
editions, with no missing days: Wikimedia's daily and monthly aggregate endpoints
disagree slightly in those reprocessed months. We use daily sums consistently for share.
The script prints pageviews.wmcloud.org links for a visual check.

**Model evals** — `tests/evals/prompts.yaml` has 14 prompts (the 3 examples,
ambiguous topic, needs-confirmation, missing language, tiny wiki, two follow-ups that
change assumptions, a composite request, Ukrainian and Polish users, a
willingness-to-pay trap, explicit dates). Run them with Haiku:

```bash
uv run python tests/evals/run_evals.py                   # all cases, claude -p --model haiku
uv run python tests/evals/run_evals.py --cases ex1-fasting-pl-cs
```

The runner installs the skill into a temp workdir (outside the repo), runs each case
(multi-turn cases continue the session), saves stream-json transcripts, and
`grade.py` checks: resolve called first, every number in the answer appears in tool
JSON, confidence label present, report PDF is one page, plus per-case expectations.
`grades.json` lists the manual checklist items.

Final clean run with Haiku 4.5 (2026-09-27): 12/14 automatic, 13/14 correct after
reading transcripts (one grader false alarm). The remaining failure: the model invented a
user confirmation, which the audit flags. Seven eval runs led to code guardrails
(confirmation enforcement, tool-computed rankings and comparisons, `--min-daily-views`);
see `docs/GUIDE.md` §6.9 and Appendix A.

## Limitations

- Pageviews measure attention on Wikipedia, not demand or willingness to pay.
- A language edition is not a country (`en`, `es`, `pt`, `ar`, `fr` span many).
- Wikipedia's share of information seeking differs by country and is changing
  (search answer boxes, AI assistants); share-of-edition partly corrects for it.
- `agent=user` still contains some automated traffic; spike detection catches bursts,
  not steady bots.
- Articles missing from Wikidata are only found via search suggestions that the user
  must confirm.
- Warnings in PDF reports are in English, even in uk/pl/cs reports (headings,
  verdicts and labels are translated).
- The Mann–Kendall p-value has no autocorrelation correction (the block-bootstrap CI
  accounts for serial dependence; both are required for a directional verdict).
- Redirects are capped at 50 per article (a warning is shown when the cap is hit).

See `ROADMAP.md` for extensions.
