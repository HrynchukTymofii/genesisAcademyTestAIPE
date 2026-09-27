"""Run an AnalysisSpec end to end: resolve -> fetch -> stats -> save run dir.

Run dir layout (./wiki-analyst-runs/<id>/):
  result.json   full results (compact records + full-precision details)
  spec.yaml     resolved spec (QIDs filled in) — copy/edit/rerun for follow-ups
  series/       <topic>_<lang>_monthly.csv and _daily.csv
  charts/       PNG charts
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from urllib.parse import quote, urlencode
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import __version__
from .api import WikimediaClient
from .errors import AmbiguousTopicError, ConfirmationRequired, ResolveError, WikiInterestError
from .resolve import Entity, domain_for, entity_info, missing_message, resolve_topic
from .series import auto_base_months, build_topic_series, indexed, parse_period
from .spec import AnalysisSpec, TopicSpec, dump_spec
from .stats import assess

RESULT_FILE = "result.json"


def runs_root() -> Path:
    return Path(os.environ.get("WIKI_ANALYST_RUNS", "wiki-analyst-runs"))


# -- pending confirmations -------------------------------------------------------------
# A rule in SKILL.md ("stop and ask after an ambiguous resolve") was followed only some of
# the time by a small model in evals, so it is enforced here: an unanswered ambiguity
# blocks analysis until the agent passes --confirmed (after the user has chosen).
PENDING_FILE = ".pending-confirmation.json"
PENDING_TTL = 6 * 3600


def _pending_path() -> Path:
    return runs_root() / PENDING_FILE


def record_pending(query: str, status: str, candidates: list[dict]) -> None:
    path = _pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [p for p in _read_pending() if p["query"] != query]
    items.append(
        {
            "query": query,
            "status": status,
            "candidates": [
                {"qid": c.get("qid"), "label": c.get("label"), "description": c.get("description")}
                for c in candidates[:6]
            ],
            "created": datetime.now().timestamp(),
        }
    )
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")


def _read_pending() -> list[dict]:
    path = _pending_path()
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    now = datetime.now().timestamp()
    return [p for p in items if now - p.get("created", 0) < PENDING_TTL]


def check_pending(confirmed: str | None) -> dict | None:
    """Raise if an ambiguity is waiting for the user.

    ``confirmed`` must quote the user's answer. It clears the pending state and is
    returned for the run's results, so a bypass is visible and auditable rather than
    silent (the tool cannot see the chat; the host app or the evals verify the quote).
    """
    items = _read_pending()
    if confirmed is not None:
        if len(confirmed.split()) < 2:
            raise ConfirmationRequired(
                "--confirmed needs the user's answer quoted (at least two words), "
                "e.g. --confirmed \"use the planet\".",
                hint="Quote what the user wrote. If the user has not answered yet, ask them first.",
            )
        _pending_path().unlink(missing_ok=True)
        return {"user_answer": confirmed, "pending": [p["query"] for p in items]}
    if items:
        p = items[-1]
        options = "; ".join(f"{c['qid']} {c['label']} — {c['description']}" for c in p["candidates"])
        raise ConfirmationRequired(
            f"'{p['query']}' is {p['status']}: the user has not chosen an entity yet. "
            f"Options: {options}",
            hint="Ask the user which one they mean (or which articles to use) and end your turn. "
            "Do not analyse a substitute topic. After the user answers (or has moved on to a "
            "different topic), rerun with --confirmed \"<the user's answer, quoted>\".",
        )
    return None


def slugify(text: str, fallback: str = "x") -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_).strip("-").lower()
    return slug[:40] or fallback


def _r(x, nd=1):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else round(float(x), nd)


def _sig(x, n=3):
    return None if x is None else float(f"{x:.{n}g}")


# -- resolution -------------------------------------------------------------------
def _resolve_topic(client, t: TopicSpec, langs: list[str], i: int) -> dict:
    """Return {label, qids, entities, titles{lang: [..]}, spec(TopicSpec resolved)}."""
    qids = t.all_qids()
    resolved_spec = t.model_copy(deep=True)
    if t.text:
        r = resolve_topic(client, t.text, langs)
        if r["status"] in ("ambiguous", "needs_confirmation"):
            record_pending(t.text, r["status"], r.get("candidates") or [r, *r.get("alternatives", [])])
        if r["status"] == "ambiguous":
            raise AmbiguousTopicError(
                f"Topic '{t.text}' (topics[{i}]) is ambiguous.",
                hint="Ask the user which entity they mean, then use --qid (or set qid: in the spec).",
                candidates=[
                    {k: c[k] for k in ("qid", "label", "description", "editions")}
                    for c in r["candidates"]
                ],
            )
        if r["status"] == "needs_confirmation":
            raise AmbiguousTopicError(
                f"Topic '{t.text}' (topics[{i}]) matched {r['qid']} ({r['label']}: "
                f"{r['description']}), which needs confirmation.",
                hint="Ask the user whether this entity is what they mean; if yes use --qid "
                f"{r['qid']} (or qid: in the spec), otherwise search a more specific name.",
                candidates=[
                    {"qid": r["qid"], "label": r["label"], "description": r["description"]}
                ]
                + [
                    {k: c[k] for k in ("qid", "label", "description", "editions")}
                    for c in r.get("alternatives", [])
                ],
            )
        if r["status"] == "not_found":
            raise ResolveError(
                f"No Wikidata entity for topic '{t.text}' (topics[{i}]).", hint=r["next_step"]
            )
        qids = [r["qid"]]
        resolved_spec.text = None
        resolved_spec.qid = r["qid"]
        resolved_spec.label = t.label or t.text
    entities: dict[str, Entity] = entity_info(client, qids, langs) if qids else {}
    titles: dict[str, list[str]] = {}
    for lang in langs:
        ts = [e.titles[lang] for e in entities.values() if e.titles.get(lang)]
        ts += [a for a in t.articles.get(lang, []) if a not in ts]
        titles[lang] = ts
    label = resolved_spec.label or " + ".join(e.label for e in entities.values()) or next(
        iter(next(iter(t.articles.values()), [])), f"topic {i + 1}"
    )
    resolved_spec.label = label
    missing = []
    for lang in langs:
        if titles[lang]:
            continue
        if entities:
            ent = next(iter(entities.values()))
            entry = {"topic": label, "lang": lang, "message": missing_message(ent, lang)}
            suggestions = client.search_titles(domain_for(lang), ent.label)
            if suggestions:
                entry["search_suggestions"] = suggestions
                entry["next_step"] = (
                    f"Not linked in Wikidata. Ask the user whether one of these {lang} articles "
                    f"covers the topic; if yes rerun with --article {lang}:'<Title>'."
                )
        else:
            entry = {"topic": label, "lang": lang, "message": f"No {lang} article given for topic '{label}'."}
        missing.append(entry)
    return {
        "label": label,
        "qids": qids,
        "titles": titles,
        "missing": missing,
        "spec": resolved_spec,
        "slug": slugify(label, fallback=(qids[0].lower() if qids else f"topic{i + 1}")),
    }


# -- per-series record -------------------------------------------------------------
def _sources(topic: dict, ts) -> dict:
    """Public pages where a human can check every number of this series."""
    start, end = ts.period.start.isoformat(), ts.period.end.isoformat()
    common = {"platform": "all-access", "agent": "user", "start": start, "end": end}
    return {
        "wikipedia": [f"https://{ts.domain}/wiki/{quote(t.replace(' ', '_'))}" for t in ts.titles],
        "wikidata": [f"https://www.wikidata.org/wiki/{q}" for q in topic["qids"]],
        # same articles and dates; "redirects=1" sums redirects like we do (verified to
        # match our totals exactly, and avoids the tool's 10-page limit)
        "pageviews": "https://pageviews.wmcloud.org/?"
        + urlencode(
            {
                **common,
                "project": ts.domain,
                "pages": "|".join(ts.titles),
                **({"redirects": "1"} if len(ts.fetched_titles) > len(ts.titles) else {}),
            }
        ),
        # whole edition, same dates: the denominator of share
        "edition_total": "https://pageviews.wmcloud.org/siteviews/?"
        + urlencode({**common, "sites": ts.domain}),
        "api": "Wikimedia Pageviews REST API (per-article and aggregate, agent=user, daily)",
    }


def _record(topic: dict, lang: str, ts, st: dict, metric: str, base_months: int | None) -> dict:
    m_metric = ts.monthly_share if metric == "share" else ts.monthly_views
    base = auto_base_months(len(m_metric), base_months)
    idx = indexed(m_metric, base)
    t, tc = st["trend"], st["trend_without_spikes"]
    other_key = "trend_raw_views" if metric == "share" else "trend_share"
    yoy = st["yoy"] or {}
    return {
        "topic": topic["label"],
        "lang": lang,
        "titles": ts.titles,
        "redirects_merged": len(ts.fetched_titles) - len(ts.titles),
        "verdict": st["verdict"],
        "confidence": st["confidence"],
        "trend_pct_per_year": _r(t["pct_per_year"]),
        "trend_ci95": [_r(t["ci_low"]), _r(t["ci_high"])],
        "mann_kendall_p": _sig(t["mk_p"]),
        "trend_without_spikes_pct_per_year": _r(tc["pct_per_year"]),
        f"{other_key}_pct_per_year": _r(st[other_key]["pct_per_year"]),
        "edition_total_trend_pct_per_year": _r(st["edition_total_trend_pct_per_year"]),
        "yoy_pct": _r(yoy.get("last12_vs_prev12_pct")),
        "same_months_up": (
            f"{yoy['same_month_up']}/{yoy['same_month_compared']}" if yoy else None
        ),
        "median_daily_views": _r(st["median_daily_views"], 0),
        "share_per_million_last12": _r(st["last12_share_per_million"], 2),
        "index_recent": _r(idx.iloc[-base:].mean()),
        "index_basis": f"mean of last {base} months; first {base} months = 100",
        "relative_to_edition": _relative_to_edition(st, lang),
        "spike_days": st["spikes"]["spike_days"],
        "seasonality_strength": _r(st["seasonality_strength"], 2),
        "months": st["months"],
        "data_from": st["data_from"],
        "reasons": st["reasons"],
        "warnings": ts.warnings + st["warnings"],
        "sources": _sources(topic, ts),
    }


def headline(rec: dict, metric: str) -> str:
    who = f"{rec['topic']} [{rec['lang']}]"
    if rec["confidence"] == "insufficient_data":
        return f"{who}: insufficient data ({rec['reasons'][0]})"
    lo, hi = rec["trend_ci95"]
    basis = "share of edition views" if metric == "share" else "raw views"
    return (
        f"{who}: {rec['verdict']} {rec['trend_pct_per_year']:+.1f}%/yr in {basis} "
        f"(95% CI {lo:+.1f}..{hi:+.1f}), confidence {rec['confidence']}"
    )


def _relative_to_edition(st: dict, lang: str) -> str:
    """The share verdict in words, so the model never needs to divide trends itself."""
    edition = f"{lang} Wikipedia overall"
    if st["metric"] != "share":
        return "see share trend (metric=raw)"
    return {
        "declining": f"losing ground: falls faster than {edition}",
        "growing": f"gaining ground: grows faster than {edition}",
        "stable": f"keeping pace with {edition}",
    }.get(st["verdict"], f"no clear difference from {edition}")


def _comparisons(spec: AnalysisSpec, records: list[dict]) -> dict:
    min_vol = spec.options.min_median_daily_views
    usable = [
        r
        for r in records
        if r["confidence"] != "insufficient_data" and (r["median_daily_views"] or 0) >= min_vol
    ]
    keys = ("trend_pct_per_year", "confidence", "verdict", "share_per_million_last12", "index_recent")
    out: dict = {}
    if "languages" in spec.effective_comparisons():
        out["languages"] = []
        for topic in dict.fromkeys(r["topic"] for r in records):
            rs = sorted(
                (r for r in usable if r["topic"] == topic),
                key=lambda r: -(r["trend_pct_per_year"] or -1e9),
            )
            if not rs:
                continue
            out["languages"].append(
                {
                    "topic": topic,
                    "ranked_by_trend": [{"lang": r["lang"], **{k: r[k] for k in keys}} for r in rs],
                    "highest_share_of_edition": max(
                        rs, key=lambda r: r["share_per_million_last12"] or 0
                    )["lang"],
                }
            )
    if "topics" in spec.effective_comparisons():
        out["topics"] = []
        for lang in spec.languages:
            rs = sorted(
                (r for r in usable if r["lang"] == lang),
                key=lambda r: -(r["trend_pct_per_year"] or -1e9),
            )
            if not rs:
                continue
            out["topics"].append(
                {
                    "lang": lang,
                    "ranked_by_trend": [{"topic": r["topic"], **{k: r[k] for k in keys}} for r in rs],
                    "highest_share_of_edition": max(
                        rs, key=lambda r: r["share_per_million_last12"] or 0
                    )["topic"],
                }
            )
    topics_n = len({r["topic"] for r in records})
    langs_n = len({r["lang"] for r in records})
    if topics_n > 1 and langs_n > 1 and len(usable) > 1:  # "which pair is best?"
        out["overall_ranked_by_trend"] = [
            {"topic": r["topic"], "lang": r["lang"], **{k: r[k] for k in keys}}
            for r in sorted(usable, key=lambda r: -(r["trend_pct_per_year"] or -1e9))
        ]
    if spec.ranking and usable:
        from .ranking import custom_ranking

        out["custom_ranking"] = custom_ranking(
            usable, dict(spec.ranking.weights), spec.ranking.min_confidence
        )
    out = {k: v for k, v in out.items() if v}  # drop empty rankings
    excluded = [f"{r['topic']} [{r['lang']}]" for r in records if r not in usable]
    if excluded and spec.effective_comparisons():
        out["excluded_from_rankings"] = excluded
        if min_vol:
            out["filter"] = f"series with median < {min_vol:g} views/day or insufficient_data are not ranked"
    if out:
        out["note"] = (
            "Rankings use growth of share of edition views (%/yr) and share level; raw counts "
            "are not comparable across editions. insufficient_data series are excluded."
        )
    return out


# -- main entry ----------------------------------------------------------------------
def new_run_dir(spec: AnalysisSpec, label_hint: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = runs_root() / f"{stamp}-{slugify(spec.name or label_hint)}"
    d, k = base, 1
    while d.exists():
        k += 1
        d = Path(f"{base}-{k}")
    (d / "series").mkdir(parents=True)
    (d / "charts").mkdir()
    return d


def run_analysis(
    spec: AnalysisSpec,
    command: str = "run",
    client: WikimediaClient | None = None,
    confirmed: str | None = None,
    note: str | None = None,
) -> dict:
    """Execute the spec. Returns the compact JSON summary (also saved in result.json)."""
    confirmation = check_pending(confirmed)
    client = client or WikimediaClient()
    period = parse_period(spec.period, spec.start, spec.end)
    topics = [_resolve_topic(client, t, spec.languages, i) for i, t in enumerate(spec.topics)]

    records, details, missing = [], [], []
    series_list = []  # aligned with records
    for topic in topics:
        missing += topic["missing"]
        for lang in spec.languages:
            if not topic["titles"][lang]:
                continue
            ts = build_topic_series(
                client,
                topic["label"],
                lang,
                domain_for(lang),
                topic["titles"][lang],
                period,
                merge_redirects=spec.options.merge_redirects,
            )
            st = assess(
                ts.daily_views,
                ts.daily_total,
                metric=spec.metric,
                spike_k=spec.options.spike_k,
                n_boot=spec.options.n_boot,
            )
            records.append(_record(topic, lang, ts, st, spec.metric, spec.options.base_months))
            details.append({"topic": topic["label"], "lang": lang, "stats": st})
            series_list.append((topic["slug"], lang, ts))

    if not records:
        raise WikiInterestError(
            "No series could be analysed: " + " ".join(m["message"] for m in missing),
            hint="Choose languages that have an article (see 'Available:' above) or add articles.",
        )

    label_hint = "-".join([topics[0]["slug"], *spec.languages])
    run_dir = new_run_dir(spec, label_hint)
    series_files = []
    for i, (slug, lang, ts) in enumerate(series_list):
        stem = f"{slug}_{lang}"
        if any(f"{stem}_monthly" in f for f in series_files):  # two topics with one label
            stem = f"{slug}-{i + 1}_{lang}"
        m = run_dir / "series" / f"{stem}_monthly.csv"
        ts.monthly_frame().to_csv(m, date_format="%Y-%m")
        ts.daily_frame().to_csv(run_dir / "series" / f"{stem}_daily.csv")
        series_files.append(m.as_posix())
        details[i]["series_file"] = f"series/{stem}_monthly.csv"
        records[i]["sources"]["data_file"] = m.as_posix()  # the exact numbers used

    resolved = spec.model_copy(deep=True)
    resolved.topics = [t["spec"] for t in topics]
    resolved.end = period.end.strftime("%Y-%m")
    dump_spec(resolved, run_dir / "spec.yaml")

    run_dir_s = run_dir.as_posix()
    summary = {
        "ok": True,
        "command": command,
        "run_dir": run_dir_s,
        "period": period.to_dict(),
        "metric": spec.metric,
        "metric_note": (
            "Trend verdicts use share of edition views (views per million), which removes "
            "changes in the edition's overall traffic."
            if spec.metric == "share"
            else "Trend verdicts use raw views; they include changes in the edition's overall traffic."
        ),
        "topics": [
            {"label": t["label"], "qids": t["qids"], "titles": t["titles"]} for t in topics
        ],
        "headline": [headline(r, spec.metric) for r in records],
        "results": records,
    }
    if note:
        summary["request"] = note  # the user's words, for `history` search
    if confirmation:
        summary["user_confirmation"] = confirmation
    comps = _comparisons(spec, records)
    if comps:
        summary["comparisons"] = comps
    if missing:
        summary["missing"] = missing
    summary["files"] = {
        "result": f"{run_dir_s}/{RESULT_FILE}",
        "spec": f"{run_dir_s}/spec.yaml",
        "series": series_files,
    }

    full = {
        **summary,
        "version": __version__,
        "created": datetime.now().isoformat(timespec="seconds"),
        "details": details,
    }
    _save(run_dir, full)

    # charts / report requested by the spec (imported lazily: matplotlib is slow to load)
    if spec.output.charts:
        from .charts import make_chart

        summary["files"]["charts"] = [
            make_chart(run_dir, kind, base_months=spec.options.base_months)
            for kind in spec.output.charts
        ]
    if spec.output.report and spec.output.report.summary:
        from .report import build_report

        rep = spec.output.report
        out = build_report(run_dir, rep.summary, lang=rep.lang, out=rep.out, chart=rep.chart)
        summary["files"]["report"] = out["report"]
    full["files"] = summary["files"]
    _save(run_dir, full)

    summary["next_steps"] = _next_steps(run_dir_s, spec, summary)
    summary["requests"] = {"http": client.requests_made, "cache_hits": client.cache_hits}
    return summary


def _next_steps(run_dir: str, spec: AnalysisSpec, summary: dict) -> list[str]:
    steps = []
    if "report" not in summary["files"]:
        steps.append(
            f'wiki-analyst report {run_dir} --summary "<2-4 sentences using numbers above>" --lang en'
        )
    steps.append(f"Follow-up: copy {run_dir}/spec.yaml, edit it, then: wiki-analyst run <spec.yaml>")
    return steps


def _save(run_dir: Path, full: dict) -> None:
    (run_dir / RESULT_FILE).write_text(
        json.dumps(full, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


def load_run(run_dir: str | Path) -> dict:
    p = Path(run_dir)
    f = p / RESULT_FILE if p.is_dir() else p
    if not f.exists():
        raise WikiInterestError(
            f"No {RESULT_FILE} in {run_dir}.",
            hint="Pass the run_dir printed by analyze/compare/run (under ./wiki-analyst-runs/).",
        )
    return json.loads(f.read_text(encoding="utf-8"))
