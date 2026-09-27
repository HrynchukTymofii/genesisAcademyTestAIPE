# Analysis spec (YAML)

Use a spec when the request has several topics, a topic made of several
articles, filters, explicit dates, or when you are following up on an earlier run.
Run it with `wiki-analyst run <spec.yaml>`. Examples: `specs/examples/`.

## Fields

| Field | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | – | Short name; used in the run dir name. |
| `topics` | list (≥1) | required | Topics to analyse; see below. |
| `languages` | list of codes (≥1) | required | Wikipedia editions, e.g. `[pl, cs]`. |
| `period` | `24m`, `36m`, `2y`… | `24m` | Months back from `end`. |
| `start` | `YYYY-MM` | – | Overrides `period`. Data exist from `2015-07`. |
| `end` | `YYYY-MM` | last complete month | Must be a complete month. |
| `metric` | `share` \| `raw` | `share` | Basis for verdicts. Keep `share` unless the user asks for raw. |
| `comparisons` | list of `languages`, `topics` | inferred | Rankings to produce. |
| `ranking.weights` | map of `growth`, `share`, `volume`, `certainty` → weight | – | The user's own criteria of promise; weights of any positive scale, normalised to 1. CLI: `--rank-by growth=0.5,share=0.3` |
| `ranking.min_confidence` | `weak` \| `moderate` \| `strong` | `weak` | Only rank series at least this certain. CLI: `--min-confidence` |
| `output.charts` | list of `indexed`, `share`, `raw` | `[indexed]` | Charts saved in the run dir. |
| `output.report.lang` | code | `en` | Report headings: `en`, `uk`, `pl`, `cs`. |
| `output.report.summary` | string | – | 2–4 sentences; only when you already know the numbers (normally use the `report` command after the run). |
| `output.report.out` | filename | `report.pdf` | Bare filename = inside the run dir. |
| `output.report.chart` | chart kind | `indexed` | Main chart in the report. |
| `options.min_median_daily_views` | number | `0` | Exclude smaller series from rankings (still reported). |
| `options.spike_k` | number | `5` | Spike threshold: median + k·MAD. |
| `options.base_months` | 1–12 | auto | Index base; auto = 12 if ≥24 months else 3. |
| `options.merge_redirects` | bool | `true` | Sum redirect views into the article. |
| `options.n_boot` | int | `1000` | Bootstrap resamples for the CI. |

## A topic

Give exactly one way to find its articles (you may add `articles` to `qid`/`qids`):

```yaml
- qid: Q333                 # one Wikidata entity (preferred; get it from `resolve`)
  label: astronomy          # optional display name
- qids: [Q487425, Q490396]  # several entities summed into ONE topic
  label: English exams
- text: astronomy           # resolved at run time; fails if ambiguous or unconfirmed
- label: fasting
  qid: Q1666254
  articles:                 # extra titles per language, summed with the entity's article
    pl: [Głodówka lecznicza]
```

`text` and `qid`/`qids` cannot be combined. Unknown fields are rejected.

## Validation errors

Errors name the exact field, e.g.
`Invalid spec: topics[1].qid: 'X5' is not a QID like Q12345; languages[0]: 'polish' is not a Wikipedia language code`.
Fix that field and rerun.

## Follow-ups

Every run saves `spec.yaml` (topics resolved to QIDs, `end` fixed) in its run dir.

- Quick edits: `wiki-analyst run <run_dir> --set period=36m --set languages=pl,cs,sk`
  (`--set` takes `key=value`; list fields take commas; nested keys use dots, e.g.
  `--set output.report.lang=uk`; setting `period` clears `start`/`end`).
- Larger edits: copy `<run_dir>/spec.yaml`, edit, `wiki-analyst run <copy>`.
- `--save-as my.yaml` writes the edited spec for later.

Data already downloaded is cached, so reruns are fast.
