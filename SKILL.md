---
name: wiki-interest
description: Analyze Wikipedia pageview trends to measure public interest in topics and compare language editions (markets). Use when the user asks whether interest in a topic is growing or declining, wants to compare interest across languages/countries or across topics, asks how trustworthy a trend is, wants charts or a one-page PDF report on topic interest, or mentions Wikipedia pageviews, Wikimedia data, market or language selection for a B2C product.
---

# wiki-interest

The tool does ALL data work and statistics. You translate the request into commands,
read the JSON they print, and write the answer. Never compute numbers yourself.

`WI` below means: `uv run --project <skill_dir> wiki-interest`
(`<skill_dir>` = the absolute path of the directory containing this file), e.g.
`uv run --project "C:/path/to/wiki-interest" wiki-interest resolve "astronomy" --langs uk`.
Run every command from the user's current directory. Never `cd` into `<skill_dir>`:
results go to `./wiki-interest-runs/<id>/` under the directory you run from.

## 1. Setup check (once per session)

1. `uv --version`. If not found, try `python -m uv --version`; if that works, use
   `python -m uv` wherever this file says `uv`. If both fail, ask the user to install
   uv (https://docs.astral.sh/uv/) and stop.
2. `WI --help` — the first call installs dependencies automatically (`uv sync`).
   If it fails with a certificate error, retry with env `UV_SYSTEM_CERTS=1`.

## 2. Workflow

1. **Resolve** every topic: `WI resolve "<topic>" --langs pl,cs`
   - `resolved` → tell the user in one line which entity you use (label + description).
     If the description clearly is not what they mean, treat it as ambiguous.
   - `needs_confirmation` or `ambiguous` → STOP and end your turn with a question.
     Show the candidates (label — description) and ask the user to choose. Do NOT
     analyze anything else instead (no broader or "closest" entity). You may propose
     options, e.g. for "learning English": exam articles summed (TOEFL + IELTS) or
     "English as a second language", but wait for the user's answer. The tool enforces
     this: analysis fails with `confirmation_required` until you pass
     `--confirmed "<the user's answer, quoted>"`, only after the user has answered.
     The quote is saved in the results and audited.
   - `not_found` → try the English name or a synonym, then ask the user.
   - `missing` languages → say so explicitly. If `search_suggestions` appear later in
     analyze output, ask the user before using one with `--article lang:Title`.
2. **Analyze** (see decision tree) with the QIDs from step 1.
3. **Read the JSON**: `headline`, `results[*]` (`verdict`, `confidence`,
   `trend_pct_per_year`, `trend_ci95`, `yoy_pct`, `reasons`, `warnings`),
   `comparisons`, `missing`.
4. **Answer in the user's language** (template below).
5. **Offer** a chart (`WI chart <run_dir> --kind indexed`) and/or a one-page report.
   Make a chart or report only when the user asks for one.

## 3. Decision tree

- One topic, one or more languages → `WI analyze --qid Q.. --langs a,b --period 24m`
  - Topic = several entities summed → repeat `--qid` (`--qid Q1 --qid Q2`).
- Several topics side by side → `WI compare --qids Q1,Q2 --langs a,b --period 24m`
- Both commands accept: `--start YYYY-MM --end YYYY-MM` (explicit dates, replace
  `--period`), `--min-daily-views N` ("ignore series under N views/day"),
  `--metric raw`.
- User states what "promising" means ("fast growth matters most, then size") →
  `--rank-by growth=0.6,share=0.4` (criteria: growth, share, volume, certainty) and
  optionally `--min-confidence moderate`. Quote `comparisons.custom_ranking`
  (rank, score, points); scores are relative 0–100 among the compared series.
- Topics with extra articles, multi-step or composite
  requests → write a spec YAML (see `references/spec-schema.md`, copy from
  `specs/examples/`) and `WI run spec.yaml`.
- Nothing above fits → short script using the library (`references/library-api.md`).

Period: user's wording ("2 years" → `24m`, "3 years" → `36m`). Default `24m`.
User gives dates ("from 2023-01 to 2025-12") → `--start 2023-01 --end 2025-12`.
Use `36m` or more when the user asks about trust or seasonality.
Use `--metric raw` only if the user explicitly asks for raw views.

## 4. Follow-ups ("add Slovak", "use 3 years", "only since 2023")

Do NOT start over. Reuse the previous run's spec:
`WI run <previous_run_dir> --set languages=pl,cs,sk --set period=36m`
For bigger changes copy `<run_dir>/spec.yaml`, edit it, `WI run <copy>`.
Cached data makes reruns fast.

## 5. Report

1. Run the analysis first and read the JSON.
2. Write 2–4 sentences: the answer, the recommendation (e.g. which audiences to
   research next and why), the main caveat. Use ONLY numbers that appear in the JSON.
3. `WI report <run_dir> --summary "<text>" --lang <user language: en|uk|pl|cs>`
4. If it returns `summary_numbers_not_in_results`, remove or fix the listed numbers
   and run it again. Give the user the `report` path.

## 6. Hard rules

- Never compute, estimate or round statistics yourself; copy numbers from the JSON.
  No derived numbers either: no differences, ratios, multiples ("2.7× faster"),
  averages or sums. Say it in words ("declines faster than the edition overall").
- Always state the `confidence` label for each claim, in English as printed, also
  when answering in another language: "впевненість: moderate (помірна)". Trends use
  **share of edition traffic** (views per million views of that Wikipedia edition);
  say so.
- Compare languages by trend %/yr, share, or index — never by raw view counts.
- Never rank or sort results yourself: use `comparisons` (`ranked_by_trend`,
  `overall_ranked_by_trend`). For "compared with the whole Wikipedia" quote
  `relative_to_edition`.
- Use command output as printed; do not reformat it (no `ConvertTo-Json`, `jq`).
- Say that pageviews signal interest, not willingness to pay.
- Quote relevant `warnings` as caveats (spikes, low volume, seasonality, edition decline).
- `insufficient_data` or `weak` → say the data cannot support a conclusion.
- Never silently choose an ambiguous entity; never invent a Wikipedia article title.
- On an error JSON, follow its `next_step`. Do not retry the same command unchanged
  more than once.
- Do not print or paste raw time series; point to the CSV files if asked.

## 7. Answer template (translate to the user's language)

> **Answer:** <verdict per language from `headline`>.
> **Numbers:** <topic> [<lang>]: <trend_pct_per_year>%/yr (95% CI <lo>..<hi>),
> last 12 vs previous 12 months <yoy_pct>%, confidence **<confidence>**.
> **Why this confidence:** <1–2 items from `reasons`>.
> **Caveats:** <relevant `warnings`>; trends use share of edition traffic;
> pageviews = interest, not willingness to pay.
> **Next:** offer chart / report / follow-up (more languages, longer period).

## 8. References (read only when needed)

- `references/interpreting.md` — what each field and label means; how to phrase answers.
- `references/methodology.md` — how the statistics and confidence are computed.
- `references/spec-schema.md` — spec YAML fields, follow-up edits.
- `references/library-api.md` — Python functions for custom cases.
- `references/languages.md` — language codes, small editions, pitfalls.
