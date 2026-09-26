"""Run an AnalysisSpec end to end: resolve -> fetch -> stats -> save run dir.

Run dir layout (./wiki-interest-runs/<id>/):
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
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import __version__
from .api import WikimediaClient
from .errors import AmbiguousTopicError, ResolveError, WikiInterestError
from .resolve import Entity, domain_for, entity_info, missing_message, resolve_topic
from .series import auto_base_months, build_topic_series, indexed, parse_period
from .spec import AnalysisSpec, TopicSpec, dump_spec
from .stats import assess

RESULT_FILE = "result.json"


def runs_root() -> Path:
    return Path(os.environ.get("WIKI_INTEREST_RUNS", "wiki-interest-runs"))


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
        if r["status"] == "ambiguous":
            raise AmbiguousTopicError(
                f"Topic '{t.text}' (topics[{i}]) is ambiguous.",
                hint="Ask the user which entity they mean, then use --qid (or set qid: in the spec).",
                candidates=[
                    {k: c[k] for k in ("qid", "label", "description", "editions")}
                    for c in r["candidates"]
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
        "spike_days": st["spikes"]["spike_days"],
        "seasonality_strength": _r(st["seasonality_strength"], 2),
        "months": st["months"],
        "data_from": st["data_from"],
        "reasons": st["reasons"],
        "warnings": ts.warnings + st["warnings"],
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
    spec: AnalysisSpec, command: str = "run", client: WikimediaClient | None = None
) -> dict:
    """Execute the spec. Returns the compact JSON summary (also saved in result.json)."""
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
            f'wiki-interest report {run_dir} --summary "<2-4 sentences using numbers above>" --lang en'
        )
    steps.append(f"Follow-up: copy {run_dir}/spec.yaml, edit it, then: wiki-interest run <spec.yaml>")
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
            hint="Pass the run_dir printed by analyze/compare/run (under ./wiki-interest-runs/).",
        )
    return json.loads(f.read_text(encoding="utf-8"))
