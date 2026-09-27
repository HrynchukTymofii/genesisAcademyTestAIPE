"""Find earlier analyses: recall that survives long chats and new sessions.

Every run folder already holds the source of truth (result.json, spec.yaml). This
module searches them by the user's original request (--note), topics, QIDs,
languages (codes and English names) and headlines, and re-prints a run's compact
results, so old numbers are re-read from disk instead of from a chat summary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .engine import RESULT_FILE, load_run, runs_root
from .errors import WikiInterestError

LANGUAGE_NAMES = {
    "en": "english", "de": "german", "fr": "french", "es": "spanish", "it": "italian",
    "pt": "portuguese", "nl": "dutch", "pl": "polish", "cs": "czech", "sk": "slovak",
    "hu": "hungarian", "ro": "romanian", "bg": "bulgarian", "sr": "serbian",
    "hr": "croatian", "sl": "slovene slovenian", "lt": "lithuanian", "lv": "latvian",
    "et": "estonian", "el": "greek", "uk": "ukrainian", "ru": "russian",
    "be": "belarusian", "kk": "kazakh", "ka": "georgian", "hy": "armenian",
    "az": "azerbaijani", "tr": "turkish", "ar": "arabic", "fa": "persian", "he": "hebrew",
    "hi": "hindi", "id": "indonesian", "vi": "vietnamese", "th": "thai",
    "ja": "japanese", "ko": "korean", "zh": "chinese", "sv": "swedish",
    "fi": "finnish", "no": "norwegian", "da": "danish", "rue": "rusyn",
}
COMPACT_KEYS = (
    "run_dir", "request", "period", "metric", "topics", "headline", "results",
    "comparisons", "missing", "files", "user_confirmation",
)


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text.lower()) if len(t) > 1]


def _entry(run_dir: Path) -> dict | None:
    try:
        r = json.loads((run_dir / RESULT_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    langs = sorted({x["lang"] for x in r.get("results", [])} | {
        lang for t in r.get("topics", []) for lang in t.get("titles", {})
    })
    return {
        "run_dir": run_dir.as_posix(),
        "created": r.get("created"),
        "command": r.get("command"),
        "request": r.get("request"),
        "topics": [t.get("label") for t in r.get("topics", [])],
        "qids": [q for t in r.get("topics", []) for q in t.get("qids", [])],
        "languages": langs,
        "period": r.get("period"),
        "headline": r.get("headline", [])[:4],
        "report": (run_dir / "report.pdf").exists() or bool(r.get("files", {}).get("report")),
        "_mtime": (run_dir / RESULT_FILE).stat().st_mtime,  # sub-second tie-breaker
    }


def _blob(e: dict) -> str:
    names = " ".join(LANGUAGE_NAMES.get(lang, "") for lang in e["languages"])
    parts = [e["request"] or "", " ".join(e["topics"]), " ".join(e["qids"]),
             " ".join(e["languages"]), names, " ".join(e["headline"])]
    return " ".join(parts).lower()


def search(query: str = "", limit: int = 8) -> dict:
    root = runs_root()
    entries = [e for d in sorted(root.glob("*/")) if (e := _entry(d))]
    q = _tokens(query)
    if q:
        scored = []
        for e in entries:
            blob_tokens = set(_tokens(_blob(e)))
            hits = sum(1 for t in q if t in blob_tokens or any(b.startswith(t) for b in blob_tokens))
            if hits:
                scored.append((hits, e["_mtime"], e))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        matches = [e for *_, e in scored]
    else:
        matches = sorted(entries, key=lambda e: e["_mtime"], reverse=True)
    for e in entries:
        e.pop("_mtime", None)
    out = {
        "ok": True,
        "command": "history",
        "query": query,
        "total_runs": len(entries),
        "matches": matches[:limit],
    }
    if matches:
        out["next_step"] = (
            "Re-read a run's numbers with: wiki-interest history --run <run_dir>. "
            "Change it with: wiki-interest run <run_dir> --set key=value."
        )
    else:
        out["next_step"] = (
            "No earlier analysis matches. Try other keywords (topic, language, QID) "
            "or run a new analysis."
        )
    return out


def show(run_dir: str) -> dict:
    """Compact results of one earlier run (the same numbers it printed originally)."""
    p = Path(run_dir)
    if not (p / RESULT_FILE).exists():
        raise WikiInterestError(
            f"No saved analysis in {run_dir}.",
            hint="Use a run_dir from `wiki-interest history <keywords>`.",
        )
    r = load_run(p)
    return {"ok": True, "command": "history", **{k: r[k] for k in COMPACT_KEYS if k in r}}
