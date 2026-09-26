"""Re-record HTTP fixtures from the live Wikimedia APIs.

    WIKI_INTEREST_TODAY=2026-09-26 uv run python tests/fixtures/record_fixtures.py

Every request made by the scenarios below is saved to tests/fixtures/http/.
Keep WIKI_INTEREST_TODAY equal to FIXED_TODAY in tests/conftest.py.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

HERE = Path(__file__).parent
HTTP_DIR = HERE / "http"


def scenarios(client):
    from wiki_interest.resolve import entity_info, resolve_topic

    resolve_topic(client, "astronomy", ["uk"])
    resolve_topic(client, "mercury", ["pl"])
    resolve_topic(client, "intermittent fasting", ["pl", "cs"])
    entity_info(client, ["Q1666254"], ["pl", "cs"])


def main() -> None:
    assert os.environ.get("WIKI_INTEREST_TODAY"), "set WIKI_INTEREST_TODAY to the fixed test date"
    shutil.rmtree(HTTP_DIR, ignore_errors=True)
    os.environ["WIKI_INTEREST_RECORD_DIR"] = str(HTTP_DIR)
    from wiki_interest.api import WikimediaClient
    from wiki_interest.cache import Cache

    client = WikimediaClient(cache=Cache(":memory:"))
    scenarios(client)
    print(f"recorded {client.requests_made} responses into {HTTP_DIR}")
    client.close()


if __name__ == "__main__":
    main()
