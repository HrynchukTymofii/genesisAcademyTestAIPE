"""HTTP client for Wikimedia APIs: retries, polite rate limiting, SQLite cache."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from . import __version__
from .cache import Cache
from .errors import ApiError

REST_BASE = "https://wikimedia.org/api/rest_v1"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
PAGEVIEWS_START = date(2015, 7, 1)  # first day with pageview data

DEFAULT_CONTACT = "https://github.com/HrynchukTymofii/genesisAcademyTestAIPE"
SHORT_TTL = 6 * 3600  # current period: refresh a few times a day
META_TTL = 7 * 24 * 3600  # Wikidata search / sitelinks / redirects


def user_agent() -> str:
    contact = os.environ.get("WIKI_ANALYST_CONTACT", DEFAULT_CONTACT)
    return f"wiki-analyst/{__version__} ({contact}) httpx/{httpx.__version__}"


def today() -> date:
    """Current date; override with WIKI_ANALYST_TODAY=YYYY-MM-DD (tests, reproducibility)."""
    env = os.environ.get("WIKI_ANALYST_TODAY")
    if env:
        return datetime.strptime(env, "%Y-%m-%d").date()
    return date.today()


def ssl_context() -> ssl.SSLContext:
    """System trust store + certifi, built without ``create_default_context`` so a
    SSLKEYLOGFILE set by antivirus TLS proxies (e.g. Avast) cannot crash OpenSSL."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_default_certs()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except (ImportError, OSError):
        pass
    return ctx


def pageview_ttl(end: date, now: date | None = None) -> float | None:
    """Permanent cache once ``end`` lies in a completed month whose data has settled."""
    now = now or today()
    first_of_month = now.replace(day=1)
    if end < first_of_month and now.day >= 3:
        return None
    return SHORT_TTL


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d") + "00"


def encode_title(title: str) -> str:
    return quote(title.replace(" ", "_"), safe="")


class WikimediaClient:
    def __init__(
        self,
        cache: Cache | None = None,
        min_interval: float = 0.05,
        max_retries: int = 4,
        backoff: float = 1.0,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.cache = cache if cache is not None else Cache()
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff = backoff
        self._last_request = 0.0
        self.requests_made = 0
        self.cache_hits = 0
        self._http = httpx.Client(
            headers={"User-Agent": user_agent(), "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
            verify=ssl_context(),
        )
        record = os.environ.get("WIKI_ANALYST_RECORD_DIR")
        self._record_dir = Path(record) if record else None

    # -- core ---------------------------------------------------------------
    def get_json(self, url: str, params: dict | None = None, ttl: float | None = SHORT_TTL):
        """GET JSON. Returns None on 404. ``ttl=None`` caches permanently."""
        full = str(httpx.URL(url, params=sorted((params or {}).items())))
        cached = self.cache.get(full)
        if cached is not None:
            self.cache_hits += 1
            status, body = cached
            return None if status == 404 else json.loads(body)

        status, body = self._fetch(full)
        self.cache.set(full, status, body, ttl)
        self._record(full, status, body)
        return None if status == 404 else json.loads(body)

    def _fetch(self, url: str) -> tuple[int, str]:
        last_err = ""
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                resp = self._http.get(url)
                self.requests_made += 1
            except httpx.TransportError as exc:
                last_err = f"network error: {exc}"
            else:
                if resp.status_code == 200:
                    return 200, resp.text
                if resp.status_code == 404:
                    return 404, resp.text or "{}"
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_err = f"HTTP {resp.status_code}"
                    retry_after = resp.headers.get("Retry-After", "")
                    if retry_after.isdigit() and attempt < self.max_retries:
                        time.sleep(min(int(retry_after), 60))
                        continue
                else:
                    raise ApiError(
                        f"Wikimedia API returned HTTP {resp.status_code} for {url}",
                        hint="Check the language code and article title; if they are valid, retry later.",
                        body=resp.text[:300],
                    )
            if attempt < self.max_retries:
                time.sleep(self.backoff * (2**attempt))
        raise ApiError(
            f"Wikimedia API request failed after {self.max_retries + 1} attempts ({last_err}): {url}",
            hint="Check internet access and retry the same command; cached data is kept, so a retry is cheap.",
        )

    def _record(self, url: str, status: int, body: str) -> None:
        """Save responses as test fixtures when WIKI_ANALYST_RECORD_DIR is set."""
        if self._record_dir is None:
            return
        self._record_dir.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".json"
        (self._record_dir / name).write_text(
            json.dumps({"url": url, "status": status, "body": body}, ensure_ascii=False),
            encoding="utf-8",
        )

    # -- pageviews ----------------------------------------------------------
    def per_article(
        self, domain: str, title: str, start: date, end: date, granularity: str = "daily"
    ) -> dict[str, int]:
        """Views per timestamp (YYYYMMDD) for one article, agent=user, all-access."""
        url = (
            f"{REST_BASE}/metrics/pageviews/per-article/{domain}/all-access/user/"
            f"{encode_title(title)}/{granularity}/{_fmt(start)}/{_fmt(end)}"
        )
        data = self.get_json(url, ttl=pageview_ttl(end))
        if data is None:  # no views recorded in range (e.g. article created later)
            return {}
        return {it["timestamp"][:8]: int(it["views"]) for it in data.get("items", [])}

    def aggregate(
        self, domain: str, start: date, end: date, granularity: str = "daily"
    ) -> dict[str, int]:
        """Total user views of a whole edition (e.g. pl.wikipedia.org)."""
        url = (
            f"{REST_BASE}/metrics/pageviews/aggregate/{domain}/all-access/user/"
            f"{granularity}/{_fmt(start)}/{_fmt(end)}"
        )
        data = self.get_json(url, ttl=pageview_ttl(end))
        if data is None:
            raise ApiError(
                f"No aggregate pageview data for {domain}.",
                hint="Check that the language code is a real Wikipedia edition (e.g. 'uk', 'pl', 'cs').",
            )
        return {it["timestamp"][:8]: int(it["views"]) for it in data.get("items", [])}

    # -- wikidata / mediawiki -----------------------------------------------
    def wikidata_search(self, text: str, language: str = "en", limit: int = 7) -> list[dict]:
        data = self.get_json(
            WIKIDATA_API,
            {
                "action": "wbsearchentities",
                "search": text,
                "language": language,
                "uselang": language,
                "type": "item",
                "limit": str(limit),
                "format": "json",
            },
            ttl=META_TTL,
        )
        return (data or {}).get("search", [])

    def wikidata_entities(self, qids: list[str], languages: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(qids), 50):
            batch = qids[i : i + 50]
            data = self.get_json(
                WIKIDATA_API,
                {
                    "action": "wbgetentities",
                    "ids": "|".join(batch),
                    "props": "labels|descriptions|sitelinks/urls",
                    "languages": "|".join(sorted(set(languages) | {"en"})),
                    "format": "json",
                },
                ttl=META_TTL,
            )
            out.update((data or {}).get("entities", {}))
        return out

    def redirects(self, domain: str, title: str, limit: int = 50) -> tuple[str, list[str]]:
        """Return (canonical title, redirect titles in namespace 0) for an article."""
        data = self.get_json(
            f"https://{domain}/w/api.php",
            {
                "action": "query",
                "titles": title,
                "prop": "redirects",
                "rdnamespace": "0",
                "rdlimit": str(limit),
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
            },
            ttl=META_TTL,
        )
        pages = (data or {}).get("query", {}).get("pages", [])
        if not pages or pages[0].get("missing"):
            return title, []
        page = pages[0]
        return page["title"], [r["title"] for r in page.get("redirects", [])]

    def search_titles(self, domain: str, text: str, limit: int = 3) -> list[str]:
        """Full-text search inside one edition (suggestions for unlinked articles)."""
        data = self.get_json(
            f"https://{domain}/w/api.php",
            {
                "action": "query",
                "list": "search",
                "srsearch": text,
                "srnamespace": "0",
                "srlimit": str(limit),
                "srprop": "",
                "format": "json",
            },
            ttl=META_TTL,
        )
        return [h["title"] for h in (data or {}).get("query", {}).get("search", [])]

    def close(self) -> None:
        self._http.close()
