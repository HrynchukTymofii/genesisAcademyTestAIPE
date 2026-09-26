# Language editions

Use Wikipedia edition codes (the subdomain of `<code>.wikipedia.org`).

## Common codes

| Code | Language | | Code | Language |
|---|---|---|---|---|
| en | English | | uk | Ukrainian |
| de | German | | ru | Russian |
| fr | French | | be | Belarusian |
| es | Spanish | | kk | Kazakh |
| it | Italian | | ka | Georgian |
| pt | Portuguese | | hy | Armenian |
| nl | Dutch | | az | Azerbaijani |
| pl | Polish | | tr | Turkish |
| cs | Czech | | ar | Arabic |
| sk | Slovak | | fa | Persian |
| hu | Hungarian | | he | Hebrew |
| ro | Romanian | | hi | Hindi |
| bg | Bulgarian | | id | Indonesian |
| sr | Serbian | | vi | Vietnamese |
| hr | Croatian | | th | Thai |
| sl | Slovene | | ja | Japanese |
| lt | Lithuanian | | ko | Korean |
| lv | Latvian | | zh | Chinese |
| et | Estonian | | sv | Swedish |
| el | Greek | | fi | Finnish |
| no | Norwegian (Bokmål) | | da | Danish |

## Pitfalls

- **Norwegian Bokmål is `no`** (not `nb`). Belarusian has two editions: `be` and
  `be-tarask`.
- **Serbo-Croatian** `sh` overlaps with `sr`, `hr`, `bs`.
- **Chinese** `zh` mixes Simplified/Traditional readers; mainland China access is limited.
- **English** `en` is read worldwide; it is a poor proxy for any single country.
  Same for `es`, `pt`, `ar`, `fr`.
- Countries where Wikipedia is blocked or where another encyclopedia dominates
  (e.g. China) are under-represented.
- **Tiny editions** (e.g. `rue`, `csb`, `szl`) often have a few views per day per
  article: expect `weak` or `insufficient_data`. Say so instead of drawing conclusions.
- Some editions have strong **bot or crawler** noise even under `agent=user`;
  spike warnings usually reveal it.
- When a language is missing for an entity, the output lists `Available:` editions and
  may give `search_suggestions`; confirm any suggestion with the user before using it
  (`--article <lang>:<Title>`).
