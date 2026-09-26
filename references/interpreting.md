# Interpreting the output

## Fields in `results[*]`

| Field | Meaning | How to say it |
|---|---|---|
| `verdict` | growing / declining / stable / unclear | "Interest is growing" |
| `confidence` | strong / moderate / weak / insufficient_data | always quote it |
| `trend_pct_per_year` | growth rate of share of edition views | "+12.3% per year" |
| `trend_ci95` | 95% interval of that rate | "(95% CI +3.1 to +20.5)" |
| `mann_kendall_p` | probability of a trend this consistent by chance | rarely needed in answers |
| `trend_without_spikes_pct_per_year` | same, viral days removed | mention if very different |
| `trend_raw_views_pct_per_year` | growth of raw views | "raw views changed by …" |
| `edition_total_trend_pct_per_year` | growth of the whole edition | explains raw vs share gap |
| `yoy_pct` | last 12 months vs previous 12 | "last 12 months were 8.1% above the year before" |
| `same_months_up` | e.g. "9/12": months higher than a year earlier | consistency signal |
| `median_daily_views` | typical daily views (raw) | size of the audience signal |
| `share_per_million_last12` | views per million views of the edition, last 12 months | compare **levels** across languages |
| `index_recent` | recent level vs the base period (=100) | "about half of the level 2 years ago" (index ≈ 50) |
| `spike_days`, `seasonality_strength` | spikes / seasonal pattern | caveats |
| `reasons` | why this confidence | quote 1–2 |
| `warnings` | caveats | quote the relevant ones |

`comparisons.languages[*].ranked_by_trend` ranks languages by growth;
`highest_share_of_edition` = the language where the topic takes the largest share of
attention. Growth and size are different questions: say which one you rank by.

## Confidence labels

- **strong** — consistent trend, adequate volume, robust to spikes. State it plainly.
- **moderate** — likely, but with a limitation (short series, lowish volume, a
  disagreement). State it and name the limitation.
- **weak** — direction not established or driven by spikes / tiny volume.
  Say "no reliable trend" rather than "growing".
- **insufficient_data** — do not draw a conclusion.

## Typical warnings and what they mean

- *growth driven by spikes in 2024-04* — a few viral days (news, TV, a meme) created
  the growth; sustained interest did not grow.
- *raw views growing but share stable* — the whole edition grew; the topic kept its
  share. For market sizing, share is the fairer signal.
- *edition total traffic declining* — fewer people use that Wikipedia overall; raw
  views understate interest; share corrects for this.
- *low volume / very low volume* — small numbers, noisy; confidence capped.
- *strong seasonality* — e.g. school year; compare same months, use ≥ 36 months.
- *no pageviews before YYYY-MM* — the article is new; early growth may just be the
  article being discovered.

## Phrasing for founders

- Pageviews show curiosity and information need, **not** willingness to pay.
- A growing share in a small edition can still be a small audience: mention
  `median_daily_views` and `share_per_million_last12` next to growth.
- "Which audience to research next": prefer strong/moderate positive or stable trends
  with high share; flag weak ones as "worth a cheap test, not a conclusion".
- A language edition is not a country (Spanish, English, Portuguese, Arabic span many).
