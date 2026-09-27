"""User-defined ranking: "which audiences look most promising by MY criteria?"

Deterministic, explainable scoring so the model never weighs results itself.
Each criterion is scaled to 0–100 across the compared series (min–max; share and
volume on a log scale because they span orders of magnitude), then combined with the
user's weights (normalised to sum to 1). Every component is reported.
"""

from __future__ import annotations

import math

from .errors import SpecError

CRITERIA = {
    "growth": "trend of share of edition views, %/yr",
    "share": "views per million edition views, last 12 months (size of interest)",
    "volume": "median daily views (absolute audience signal)",
    "certainty": "confidence label (strong > moderate > weak)",
}
CONFIDENCE_ORDER = {"insufficient_data": 0, "weak": 1, "moderate": 2, "strong": 3}
METHOD = (
    "each criterion scaled 0-100 across the ranked series (share and volume on a log "
    "scale); score = weighted sum with weights normalised to 1. Scores are relative: "
    "0 = lowest among the compared series, 100 = highest, not good or bad in absolute terms"
)


def parse_weights(text: str) -> dict[str, float]:
    """'growth=0.5,share=0.3,volume=20' -> {'growth': 0.5, ...} (any positive scale)."""
    out: dict[str, float] = {}
    for part in [p.strip() for p in text.split(",") if p.strip()]:
        key, sep, val = part.partition("=")
        key = key.strip().lower()
        try:
            weight = float(val) if sep else float("nan")
        except ValueError:
            weight = float("nan")
        if key not in CRITERIA or not sep or math.isnan(weight):
            raise SpecError(
                f"--rank-by '{part}' not understood.",
                hint=f"Use criterion=weight pairs from {', '.join(CRITERIA)}, "
                "e.g. --rank-by growth=0.5,share=0.3,certainty=0.2",
            )
        out[key] = weight
    return out


def _value(rec: dict, criterion: str) -> float | None:
    if criterion == "growth":
        return rec.get("trend_pct_per_year")
    if criterion == "share":
        v = rec.get("share_per_million_last12")
        return None if v is None else math.log10(v + 0.01)
    if criterion == "volume":
        v = rec.get("median_daily_views")
        return None if v is None else math.log10(v + 1)
    return float(CONFIDENCE_ORDER.get(rec.get("confidence"), 0))


def custom_ranking(records: list[dict], weights: dict[str, float], min_confidence: str = "weak") -> dict:
    total = sum(weights.values())
    w = {k: v / total for k, v in weights.items() if v > 0}
    floor = CONFIDENCE_ORDER[min_confidence]
    ranked_in = [r for r in records if CONFIDENCE_ORDER.get(r["confidence"], 0) >= max(1, floor)]
    excluded = [
        f"{r['topic']} [{r['lang']}]: confidence {r['confidence']}"
        for r in records
        if r not in ranked_in
    ]
    points: dict[int, dict[str, float]] = {i: {} for i in range(len(ranked_in))}
    for crit in w:
        vals = [_value(r, crit) for r in ranked_in]
        known = [v for v in vals if v is not None]
        lo, hi = (min(known), max(known)) if known else (0.0, 0.0)
        for i, v in enumerate(vals):
            if v is None:
                points[i][crit] = 0.0
            elif hi == lo:
                points[i][crit] = 50.0  # no difference on this criterion
            else:
                points[i][crit] = (v - lo) / (hi - lo) * 100
    rows = []
    for i, r in enumerate(ranked_in):
        score = sum(w[c] * points[i][c] for c in w)
        rows.append(
            {
                "topic": r["topic"],
                "lang": r["lang"],
                "score": round(score, 1),
                "points": {c: round(p, 1) for c, p in points[i].items()},
                "trend_pct_per_year": r["trend_pct_per_year"],
                "share_per_million_last12": r["share_per_million_last12"],
                "median_daily_views": r["median_daily_views"],
                "confidence": r["confidence"],
            }
        )
    rows.sort(key=lambda x: -x["score"])
    for n, row in enumerate(rows, start=1):
        row["rank"] = n
    out = {
        "weights": {c: round(v, 3) for c, v in w.items()},
        "criteria": {c: CRITERIA[c] for c in w},
        "min_confidence": min_confidence,
        "method": METHOD,
        "ranked": rows,
    }
    if excluded:
        out["excluded"] = excluded
    if len(rows) < 2:
        out["note"] = "fewer than 2 series to rank; scores are not comparative"
    return out
