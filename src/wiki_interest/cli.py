"""Command line interface. Every command prints ONE compact JSON object to stdout."""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer

from .api import WikimediaClient
from .errors import WikiInterestError
from .resolve import resolve_topic, validate_langs

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
        if out["status"] == "resolved":
            out["next_step"] = (
                f"wiki-interest analyze --qid {out['qid']} --langs {langs} --period 24m"
            )
        return out

    _run(go)


if __name__ == "__main__":
    app()
