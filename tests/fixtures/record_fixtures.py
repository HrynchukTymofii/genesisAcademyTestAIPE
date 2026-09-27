"""Re-record HTTP fixtures from the live Wikimedia APIs.

    WIKI_ANALYST_TODAY=2026-09-26 uv run python tests/fixtures/record_fixtures.py

Every request made by the scenarios below is saved to tests/fixtures/http/.
Keep WIKI_ANALYST_TODAY equal to FIXED_TODAY in tests/conftest.py.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
HTTP_DIR = HERE / "http"
sys.path.insert(0, str(HERE))


def library_scenarios(client):
    from wiki_analyst.resolve import entity_info, resolve_topic
    from wiki_analyst.series import build_topic_series, parse_period

    resolve_topic(client, "astronomy", ["uk"])
    resolve_topic(client, "mercury", ["pl"])
    resolve_topic(client, "intermittent fasting", ["pl", "cs"])
    entity_info(client, ["Q1666254"], ["pl", "cs"])
    build_topic_series(
        client, "astronomy", "uk", "uk.wikipedia.org", ["Астрономія"], parse_period("24m")
    )


def main() -> None:
    assert os.environ.get("WIKI_ANALYST_TODAY"), "set WIKI_ANALYST_TODAY to the fixed test date"
    shutil.rmtree(HTTP_DIR, ignore_errors=True)
    os.environ["WIKI_ANALYST_RECORD_DIR"] = str(HTTP_DIR)
    from typer.testing import CliRunner

    from scenarios import CLI_SCENARIOS
    from wiki_analyst.api import WikimediaClient
    from wiki_analyst.cache import Cache
    from wiki_analyst.cli import app

    client = WikimediaClient(cache=Cache(":memory:"))
    library_scenarios(client)
    client.close()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        os.environ["WIKI_ANALYST_CACHE"] = str(Path(tmp) / "cache.sqlite")
        os.environ["WIKI_ANALYST_RUNS"] = str(Path(tmp) / "runs")
        runner = CliRunner()
        for name, args in CLI_SCENARIOS.items():
            res = runner.invoke(app, args)
            print(f"{name}: exit {res.exit_code}")
    print(f"recorded {len(list(HTTP_DIR.glob('*.json')))} responses into {HTTP_DIR}")


if __name__ == "__main__":
    main()
