# wiki-interest

An Agent Skill (Claude Code format) that uses Wikipedia pageviews to help B2C founders
decide **which topics to develop and which language markets to launch in**. It fetches
data, computes trend statistics you can trust, cites checkable sources, draws charts and
writes a one-page PDF report.

It is designed to be driven by a small, cheap model (Claude Haiku 4.5). The code does
all data work and statistics. The model only translates requests into commands, reads
compact JSON, and writes the answer.

```
wiki-interest resolve "astronomy" --langs uk
wiki-interest analyze --qid Q333 --langs uk --period 36m
→ astronomy [uk]: declining -47.1%/yr in share of edition views (95% CI -53.2..-41.4), confidence strong
```

## How it works

1. **Trigger.** Claude Code sees the skill's description; when a request matches, it
   loads `SKILL.md` (workflow, decision tree, hard rules).
2. **Resolve.** `resolve` maps the topic to a Wikidata entity and the article in each
   language. Ambiguous topics are **blocked** until the user chooses.
3. **Analyse.** `analyze` / `compare` / `run` fetch daily views (redirects merged),
   divide by the whole edition's traffic (share), and compute the trend, a 95% range and
   a confidence label with reasons and warnings.
4. **Answer.** Compact JSON comes back; the model answers with the verdict, numbers,
   confidence, caveats and **sources** (links where every number can be checked).
5. **Chart / PDF** on request; the PDF rejects any number the model invents.
6. **Follow-ups** reuse the saved settings of the previous run; `history` finds earlier
   analyses, also in a new chat.

## Setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 and all
dependencies from `uv.lock` on first run) and internet access.

```bash
# install as a personal Claude Code skill
git clone https://github.com/HrynchukTymofii/genesisAcademyTestAIPE.git ~/.claude/skills/wiki-interest
uv run --project ~/.claude/skills/wiki-interest wiki-interest --help   # first run installs dependencies
```

Then start `claude` in any folder and ask, e.g. "Is interest in astronomy growing in
Ukrainian Wikipedia?", or type `/wiki-interest <question>`. The model runs every command
as `uv run --project <skill_dir> wiki-interest <command>` from your current folder;
results go to `./wiki-interest-runs/<id>/`.

Environment variables (all optional):

| Variable | Default | Purpose |
|---|---|---|
| `WIKI_INTEREST_CONTACT` | repo URL | Contact info in the User-Agent (Wikimedia policy). Set to your email/URL. |
| `WIKI_INTEREST_CACHE` | `~/.cache/wiki-interest/cache.sqlite` | Response cache. |
| `WIKI_INTEREST_RUNS` | `./wiki-interest-runs` | Where run folders are created. |
| `WIKI_INTEREST_TODAY` | today | Fix "today" (reproducible runs, tests). |

**Windows and corporate/antivirus TLS notes**
- If the first run fails with `invalid peer certificate: UnknownIssuer`, set
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
| `analyze --qid Q.. [--qid ..] --langs .. --period 24m` | One topic (several entities/articles are summed) across languages. Options: `--start/--end YYYY-MM`, `--metric share\|raw`, `--article lang:Title`. |
| `compare --qids Q1,Q2 --langs .. --period 36m` | Several topics side by side. |
| `… --rank-by growth=0.6,share=0.4 [--min-confidence moderate]` | Rank by the user's own criteria (growth, share, volume, certainty), with explained scores. |
| `… --min-daily-views 10` | Leave tiny series out of rankings. |
| `… --note "<user request>"` | Store the request so the run can be found later. |
| `… --confirmed "<user's answer>"` | Continue after an ambiguous topic, quoting the user's choice (saved and audited). |
| `run <spec.yaml\|run_dir> [--set key=value]` | Composite requests and follow-ups from a YAML spec. |
| `history "<keywords>"` / `history --run <run_dir>` | Find earlier analyses and re-read their saved numbers. |
| `chart <run_dir> --kind indexed\|share\|raw` | PNG chart. |
| `report <run_dir> --summary "…" --lang en\|uk\|pl\|cs` | One-page PDF with a clickable Sources section. |

Every command prints **one compact JSON object** (key numbers, confidence label,
reasons, warnings, rankings, sources, file paths, next steps), never raw time series.
Errors are JSON too, with a `next_step` a model can follow, e.g.
`"No pl article for Q1666254 (intermittent fasting). Available: en, de, fr, es, ru, …"`.

## Design

```
SKILL.md ──► the model: resolve → confirm → analyze/compare/run → read JSON → answer (+ sources) → chart/report
                  │
src/wiki_interest/
  cli.py      typer commands, JSON in/out, errors → JSON
  engine.py   runs a spec end to end; run folder (result.json, spec.yaml, series/, charts/);
              rankings, sources, pending confirmations
  spec.py     pydantic spec; errors name the exact field; --set overrides
  resolve.py  Wikidata search + sitelinks; ambiguity policy
  series.py   per-article daily views, redirect merging, edition totals, share, index
  stats.py    Theil–Sen + block-bootstrap CI, Mann–Kendall, YoY, spikes, STL, confidence
  ranking.py  the user's weighted criteria → explained scores
  history.py  search and re-read earlier runs
  charts.py   matplotlib line charts
  report.py   reportlab one-page PDF, en/uk/pl/cs headings, summary number guard
  api.py      httpx client: retries, backoff, rate limit, User-Agent, SQLite cache (cache.py)
references/   loaded by the model only when needed (methodology, interpreting, spec schema, …)
specs/examples/  one spec per example request from the task
```

Key decisions:
- **Code computes, the model explains.** Every number comes from tested code as JSON.
- **Share of edition traffic by default.** Whole Wikipedia editions gain and lose
  traffic (e.g. uk −25.5%/yr, cs −14.7%/yr), so raw views mislead. Verdicts use views per
  million edition views; raw views are shown alongside, and disagreements become warnings.
- **Cross-language comparisons** use growth rates, share, or an index (base = 100),
  never raw counts. The index compares the first and last 12 months when there are
  ≥ 24 months, so seasonality (school year) does not distort it.
- **Redirects are merged** (summed), so renames do not create fake growth; a topic can
  be a set of articles (e.g. TOEFL + IELTS + ESL for "learning English").
- **Confidence is computed, not judged:** strong / moderate / weak / insufficient_data
  plus machine-generated reasons and warnings (`references/methodology.md`).
- **Every answer is checkable:** each result carries `sources` (Wikipedia article,
  Wikidata entity, pageviews.wmcloud.org links for the same articles, dates and the edition
  total, and the data file). Checked by hand: the public pages show exactly our totals.
- **Rules that matter are enforced in code, not only in the prompt** (testing on Haiku
  showed prompt rules hold only most of the time):
  - ambiguous topics block analysis until `--confirmed "<user's answer>"`;
  - the tool supplies rankings (`overall_ranked_by_trend`, `custom_ranking`) and
    comparisons in words (`relative_to_edition`), so the model never computes them;
  - the PDF rejects numbers not in the results.
- **Follow-ups edit the saved spec** (`run <run_dir> --set languages=pl,cs,sk`); the
  cache makes reruns nearly free (a repeated 6-language, 3-year run: 0 HTTP requests,
  121 cache hits).
- **Caching:** calendar-year request chunks; completed years cached permanently, the
  current year for 6 h, Wikidata lookups for 7 days.

## How it was tested

**Unit and integration tests**: `uv run pytest` (91 tests, no network).
- Statistics on synthetic series of known shape: flat, linear growth, flat + single
  spike, spikes that fake growth, seasonal, edition growth (raw up / share flat), low
  volume, short series, article created mid-period; exact Theil–Sen on a line with a
  known +50%/yr rate.
- API client: retries/backoff, 404 handling, caching, TTLs, User-Agent.
- Resolve, series, CLI, spec, ranking, history, sources and report tests replay **real
  recorded API responses** (`tests/fixtures/http/`, re-recorded with
  `tests/fixtures/record_fixtures.py`) via respx.
- Report: one page with a very long summary, Cyrillic font embedded, clickable sources,
  number guard (including that digits inside links are ignored).

**Cross-check against pageviews.wmcloud.org**: `uv run python tests/evals/cross_check.py`
compares our daily-summed monthly numbers with independent requests to the Wikimedia
monthly endpoint (what pageviews.wmcloud.org displays), 2025-01..2026-08:

| Case | Article views | Edition totals |
|---|---|---|
| pl `Astronomia` | exact match all 20 months (2026-08: 1 038) | max diff 0.25% |
| cs `Přerušovaný půst` | exact match (2026-08: 119) | max diff 0.29% |
| uk `Астрономія` + redirect `Astronomy` | exact match (2026-08: 362) | max diff 0.13% |

The small edition-total differences occur only in 2025-03 and 2026-04, in all
editions, with no missing days: Wikimedia's daily and monthly aggregate endpoints
disagree slightly in those reprocessed months. We use daily sums consistently for share.
The source links were also opened in a browser: uk astronomy 23,326 views, en astronomy
684,376 and the whole uk edition 1,578,771,125 views (2024-09..2026-08) match our totals exactly.

**Model evals**: `tests/evals/prompts.yaml` has 15 realistic prompts: the 3 task
examples, an ambiguous topic, a misleading topic, a tiny wiki, two follow-ups that change
assumptions, a composite request with a filter, Ukrainian and Polish users, a
willingness-to-pay trap, explicit dates, the user's own ranking criteria, and recalling
an earlier analysis in a new session. Run them with Haiku:

```bash
uv run python tests/evals/run_evals.py                   # all cases, claude -p --model haiku
uv run python tests/evals/run_evals.py --cases ex1-fasting-pl-cs
```

The runner installs the skill into a temp folder, runs each case through Claude Code
(multi-turn cases continue the session, or start fresh sessions), and saves the
transcripts. `grade.py` checks automatically: `resolve` called first; every number in
the answer appears in the tool output; a confidence label is stated; sources are cited;
any PDF is one page; the model stopped after an ambiguous topic; any `--confirmed` quote
really comes from the user; plus per-case expectations. Every failing transcript was also
read by hand.

Results with Haiku 4.5 (2026-09-27): final clean run of the first 14 prompts 13/14
correct after manual review; later-added prompts (custom criteria, history in a new
session, source citations) pass after one fix each. The remaining known failure: the
model once invented a user confirmation, which the audit flags. The eval runs drove the
code guardrails listed under Design.

## Limitations

- Pageviews measure attention on Wikipedia, not demand or willingness to pay.
- Part of Wikipedia's audience moved to AI assistants and search answers, unevenly by
  topic (factual and school topics more). Share corrects the edition-wide drop but not
  these topic differences, so a falling share can mean fewer Wikipedia lookups rather
  than less interest; comparing options is more reliable than absolute declines.
- A language edition is not a country (`en`, `es`, `pt`, `ar`, `fr` span many).
- A topic is measured through the chosen articles (by default the main article plus its
  redirects); related articles count only if added. Articles missing from Wikidata are
  found via search suggestions the user must confirm.
- `agent=user` still contains some automated traffic; spike detection catches bursts,
  not steady bots.
- The number guard proves a number exists in the results, not that it is attached to
  the right claim; chat answers are checked by the evals, not live.
- The tool cannot see the chat, so a `--confirmed` quote is audited, not proven.
- Warnings in PDF reports are in English, even in uk/pl/cs reports (headings,
  verdicts and labels are translated).
- The Mann–Kendall p-value has no autocorrelation correction (the block-bootstrap CI
  accounts for serial dependence; both are required for a directional verdict).
- Redirects are capped at 50 per article (a warning is shown when the cap is hit).
- Requests to Wikimedia are sequential; large scans need the bulk-dump approach.

See `ROADMAP.md` for how to extend it.
