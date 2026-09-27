"""Command line interface. Every command prints ONE compact JSON object to stdout."""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer

from .api import WikimediaClient
from .errors import WikiInterestError
from .resolve import resolve_topic, validate_langs
from .spec import validate_spec

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Wikipedia pageview trends for topic and language-market decisions. Output is JSON.",
)


@app.callback()
def main() -> None:
    """Wikipedia pageview trends. Start with `resolve`, then `analyze`/`compare`/`run`."""


def emit(obj: dict) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # Cyrillic etc. on Windows consoles
    except AttributeError:
        pass
    print(json.dumps(obj, ensure_ascii=False, indent=1))


def _run(fn, *args, **kwargs) -> None:
    try:
        out = fn(*args, **kwargs)
    except WikiInterestError as exc:
        emit(exc.to_dict())
        raise typer.Exit(1)
    except Exception as exc:  # never dump a traceback on the model
        emit(
            {
                "ok": False,
                "error": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
                "next_step": "Retry once; if it fails again, report this message to the user.",
            }
        )
        raise typer.Exit(2)
    emit(out)


def _split(value: Optional[str]) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@app.command()
def resolve(
    topic: str = typer.Argument(..., help="Topic text in any language, or a QID."),
    langs: str = typer.Option("en", "--langs", help="Comma-separated Wikipedia language codes."),
    limit: int = typer.Option(7, help="Max candidates to show."),
):
    """Find the Wikidata entity for a topic and its article title in each language."""

    def go():
        client = WikimediaClient()
        out = resolve_topic(client, topic, validate_langs(_split(langs)), limit=limit)
        out = {"ok": True, "command": "resolve", **out}
        if out["status"] in ("resolved", "needs_confirmation"):
            cmd = f"wiki-interest analyze --qid {out['qid']} --langs {langs} --period 24m"
            out["next_step"] = cmd if out["status"] == "resolved" else "Confirm with the user, then: " + cmd
        return out

    _run(go)


def _period_fields(period, start, end, metric) -> dict:
    d = {"period": period, "metric": metric}
    if start:
        d["start"] = start
    if end:
        d["end"] = end
    return d


def _charts(charts: str) -> list[str]:
    return _split(charts)


@app.command()
def analyze(
    qid: list[str] = typer.Option([], "--qid", help="Wikidata QID; repeat to sum several entities into one topic."),
    topic: Optional[str] = typer.Option(None, "--topic", help="Topic text (must resolve unambiguously). Prefer --qid."),
    article: list[str] = typer.Option([], "--article", help="Extra article as lang:Title; repeatable."),
    label: Optional[str] = typer.Option(None, "--label", help="Display name for the topic."),
    langs: str = typer.Option(..., "--langs", help="Comma-separated language codes, e.g. pl,cs."),
    period: str = typer.Option("24m", "--period", help="Months/years back from last complete month: 24m, 3y."),
    start: Optional[str] = typer.Option(None, "--start", help="YYYY-MM (overrides --period)."),
    end: Optional[str] = typer.Option(None, "--end", help="YYYY-MM (default: last complete month)."),
    metric: str = typer.Option("share", "--metric", help="share (default, for verdicts) or raw."),
    charts: str = typer.Option("", "--charts", help="Also draw charts: indexed,share,raw."),
):
    """One topic (one or more entities/articles summed) across one or more languages."""

    def go():
        from .engine import run_analysis

        arts: dict[str, list[str]] = {}
        for a in article:
            lang, sep, title = a.partition(":")
            if not sep or not title.strip():
                from .errors import SpecError

                raise SpecError(f"--article '{a}' must look like lang:Title", hint="e.g. --article pl:Post")
            arts.setdefault(lang.strip().lower(), []).append(title.strip())
        t: dict = {"label": label}
        if topic:
            t["text"] = topic
        if qid:
            t["qid"], t["qids"] = qid[0], qid[1:]
        if arts:
            t["articles"] = arts
        spec = validate_spec(
            {
                "topics": [t],
                "languages": _split(langs),
                **_period_fields(period, start, end, metric),
                "output": {"charts": _charts(charts)},
            }
        )
        return run_analysis(spec, command="analyze")

    _run(go)


@app.command()
def compare(
    qids: str = typer.Option(..., "--qids", help="Comma-separated QIDs; each is a separate topic."),
    langs: str = typer.Option(..., "--langs", help="Comma-separated language codes."),
    period: str = typer.Option("24m", "--period"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
    metric: str = typer.Option("share", "--metric"),
    charts: str = typer.Option("", "--charts", help="Also draw charts: indexed,share,raw."),
):
    """Several topics side by side in one or more languages."""

    def go():
        from .engine import run_analysis

        spec = validate_spec(
            {
                "topics": [{"qid": q} for q in _split(qids)],
                "languages": _split(langs),
                **_period_fields(period, start, end, metric),
                "output": {"charts": _charts(charts)},
            }
        )
        return run_analysis(spec, command="compare")

    _run(go)


@app.command()
def run(
    spec_path: str = typer.Argument(..., help="spec.yaml, or a previous run dir (reuses its spec)."),
    set_: list[str] = typer.Option([], "--set", help="Override: key=value, e.g. period=36m, languages=pl,cs,sk."),
    save_as: Optional[str] = typer.Option(None, "--save-as", help="Also write the edited spec to this path."),
):
    """Run a YAML analysis spec (composite requests, follow-ups)."""

    def go():
        from .engine import run_analysis
        from .spec import dump_spec, load_spec

        spec = load_spec(spec_path, set_)
        if save_as:
            from pathlib import Path

            dump_spec(spec, Path(save_as))
        return run_analysis(spec, command="run")

    _run(go)


@app.command()
def chart(
    run_dir: str = typer.Argument(..., help="Run dir printed by analyze/compare/run."),
    kind: str = typer.Option("indexed", "--kind", help="indexed (default), share or raw."),
):
    """Draw a chart for all series of a run; prints the PNG path."""

    def go():
        from .charts import MAX_SERIES, make_chart, omitted_series

        path = make_chart(run_dir, kind)
        out = {"ok": True, "command": "chart", "kind": kind, "chart": path}
        n = omitted_series(run_dir)
        if n:
            out["warnings"] = [
                f"chart shows the first {MAX_SERIES} series; {n} more are not drawn. "
                "Split the request (fewer topics or languages per run) for readable charts."
            ]
        return out

    _run(go)


@app.command()
def report(
    run_dir: str = typer.Argument(..., help="Run dir printed by analyze/compare/run."),
    summary: str = typer.Option(..., "--summary", help="2-4 sentences: answer, recommendation, caveat. Numbers must come from the run JSON."),
    lang: str = typer.Option("en", "--lang", help="Report language: en, uk, pl, cs (headings)."),
    out: str = typer.Option("report.pdf", "--out", help="Bare filename = inside the run dir."),
    chart: str = typer.Option("indexed", "--chart", help="Main chart kind: indexed, share, raw."),
):
    """Build the one-page PDF report."""

    def go():
        from .report import build_report

        return build_report(run_dir, summary, lang=lang, out=out, chart=chart)

    _run(go)


if __name__ == "__main__":
    app()
