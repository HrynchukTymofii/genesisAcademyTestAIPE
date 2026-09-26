"""Topic text -> Wikidata entity (QID) -> per-language Wikipedia article titles.

Never silently picks an ambiguous entity: when several plausible entities exist,
``resolve_topic`` returns status "ambiguous" with the candidates so the agent can
ask the user.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from .api import WikimediaClient
from .errors import MissingArticleError, ResolveError

QID_RE = re.compile(r"^Q\d+$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)*$")

# Big editions listed first when suggesting alternatives.
PREFERRED_ORDER = [
    "en", "de", "fr", "es", "ru", "it", "pl", "uk", "ja", "zh", "pt", "nl", "sv",
    "cs", "sk", "hu", "ro", "tr", "ar", "fa", "ko", "vi", "id", "he", "fi", "no",
    "da", "bg", "sr", "hr", "lt", "lv", "et", "el", "be", "kk",
]
DOMINANCE_RATIO = 4.0  # exact-match candidate must have 4x the sitelinks of the next one
MIN_DOMINANT_SITELINKS = 10


@dataclass
class Entity:
    qid: str
    label: str
    description: str
    sitelinks_total: int  # number of Wikipedia editions with an article (popularity proxy)
    titles: dict[str, str | None] = field(default_factory=dict)  # requested lang -> title
    domains: dict[str, str] = field(default_factory=dict)  # requested lang -> domain
    available_langs: list[str] = field(default_factory=list)
    exact_match: bool = False

    @property
    def missing_langs(self) -> list[str]:
        return [lang for lang, t in self.titles.items() if t is None]

    def compact(self) -> dict:
        d = asdict(self)
        d.pop("domains")
        d["missing_langs"] = self.missing_langs
        d["available_langs"] = sort_langs(self.available_langs)[:15]
        d["available_langs_total"] = len(self.available_langs)
        return d


def sort_langs(langs: list[str]) -> list[str]:
    rank = {code: i for i, code in enumerate(PREFERRED_ORDER)}
    return sorted(langs, key=lambda c: (rank.get(c, len(rank)), c))


def validate_langs(langs: list[str]) -> list[str]:
    out = []
    for raw in langs:
        code = raw.strip().lower()
        if not code:
            continue
        if not LANG_RE.match(code):
            raise ResolveError(
                f"'{raw}' is not a Wikipedia language code.",
                hint="Use edition codes like en, pl, cs, uk, de (see references/languages.md).",
            )
        if code not in out:
            out.append(code)
    if not out:
        raise ResolveError("No languages given.", hint="Pass --langs, e.g. --langs pl,cs")
    return out


def domain_for(lang: str) -> str:
    return f"{lang}.wikipedia.org"


def _wikipedia_sitelinks(raw_entity: dict) -> dict[str, tuple[str, str]]:
    """lang code -> (title, domain) for Wikipedia sitelinks only (not wikiquote etc.)."""
    out = {}
    for link in raw_entity.get("sitelinks", {}).values():
        host = urlparse(link.get("url", "")).netloc
        if host.endswith(".wikipedia.org"):
            lang = host[: -len(".wikipedia.org")]
            out[lang] = (link["title"], host)
    return out


def _label(raw: dict, key: str, langs: list[str]) -> str:
    values = raw.get(key, {})
    for lang in ["en", *langs]:
        if lang in values:
            return values[lang]["value"]
    return next(iter(values.values()), {}).get("value", "")


def entity_info(client: WikimediaClient, qids: list[str], langs: list[str]) -> dict[str, Entity]:
    """Fetch labels and per-language titles for QIDs. Raises for unknown QIDs."""
    for q in qids:
        if not QID_RE.match(q):
            raise ResolveError(
                f"'{q}' is not a Wikidata QID.",
                hint="QIDs look like Q12345. Run `resolve \"<topic>\"` to find one.",
            )
    raw = client.wikidata_entities(qids, langs)
    out = {}
    for q in qids:
        ent = raw.get(q)
        if ent is None or "missing" in ent:
            raise ResolveError(
                f"Wikidata entity {q} does not exist.",
                hint="Run `resolve \"<topic>\"` to find the right QID.",
            )
        if "redirects" in ent:  # merged entity: Wikidata returns the target
            ent = raw.get(ent["redirects"]["to"], ent)
        links = _wikipedia_sitelinks(ent)
        out[q] = Entity(
            qid=q,
            label=_label(ent, "labels", langs),
            description=_label(ent, "descriptions", langs),
            sitelinks_total=len(links),
            titles={lang: links[lang][0] if lang in links else None for lang in langs},
            domains={lang: links[lang][1] if lang in links else domain_for(lang) for lang in langs},
            available_langs=sorted(links),
        )
    return out


def missing_message(entity: Entity, lang: str) -> str:
    avail = ", ".join(sort_langs(entity.available_langs)[:12]) or "none"
    return f"No {lang} article for {entity.qid} ({entity.label}). Available: {avail}."


def require_titles(entity: Entity) -> None:
    """Raise if the entity has no article in any requested language."""
    if all(t is None for t in entity.titles.values()):
        langs = ", ".join(entity.titles)
        raise MissingArticleError(
            f"{entity.qid} ({entity.label}) has no article in any requested language ({langs}).",
            hint=f"Pick other languages. {missing_message(entity, langs)}",
        )


def _is_disambiguation(desc: str) -> bool:
    d = desc.lower()
    return "disambiguation page" in d or "wikimedia disambiguation" in d


def resolve_topic(
    client: WikimediaClient, text: str, langs: list[str], limit: int = 7
) -> dict:
    """Search Wikidata for ``text`` and decide whether one entity is clearly meant.

    Returns a dict with ``status``: "resolved" (one dominant exact match),
    "ambiguous" (ask the user to choose) or "not_found".
    """
    text = text.strip()
    if not text:
        raise ResolveError("Empty topic.", hint='Pass a topic, e.g. resolve "astronomy" --langs uk')
    if QID_RE.match(text.upper()):
        ents = entity_info(client, [text.upper()], langs)
        ent = ents[text.upper()]
        ent.exact_match = True
        return _result("resolved", text, ent, [ent], "Given as QID.")

    order: list[str] = []
    exact: set[str] = set()
    for lang in dict.fromkeys(["en", *langs]):
        for hit in client.wikidata_search(text, language=lang, limit=limit):
            qid = hit["id"]
            if qid not in order:
                order.append(qid)
            match_text = hit.get("match", {}).get("text", "")
            if match_text.casefold() == text.casefold():
                exact.add(qid)
    if not order:
        return {
            "status": "not_found",
            "query": text,
            "message": f"No Wikidata entity matches '{text}'.",
            "next_step": "Try an English or simpler name, a synonym, or the name in the target language.",
            "candidates": [],
        }

    info = entity_info(client, order[:20], langs)
    cands = [e for e in (info[q] for q in order[:20]) if not _is_disambiguation(e.description)]
    for e in cands:
        e.exact_match = e.qid in exact
    cands.sort(key=lambda e: (not e.exact_match, -e.sitelinks_total))
    cands = cands[:limit]
    if not cands:
        return {
            "status": "not_found",
            "query": text,
            "message": f"Only disambiguation pages match '{text}'.",
            "next_step": "Ask the user which meaning they want and search for that more specific name.",
            "candidates": [],
        }

    top = cands[0]
    exact_others = [e for e in cands[1:] if e.exact_match]
    if top.exact_match and (
        not exact_others
        or (
            top.sitelinks_total >= DOMINANCE_RATIO * max(1, exact_others[0].sitelinks_total)
            and top.sitelinks_total >= MIN_DOMINANT_SITELINKS
        )
    ):
        why = (
            "Only exact match."
            if not exact_others
            else f"Exact match with {top.sitelinks_total} Wikipedia editions vs "
            f"{exact_others[0].sitelinks_total} for the next exact match."
        )
        return _result("resolved", text, top, cands, why)
    return _result(
        "ambiguous",
        text,
        None,
        cands,
        "Several entities could match. Ask the user which one they mean (show label + description), "
        "then run analyze with --qid.",
    )


def _result(status: str, text: str, chosen: Entity | None, cands: list[Entity], why: str) -> dict:
    out: dict = {"status": status, "query": text}
    if chosen is not None:
        out["qid"] = chosen.qid
        out["label"] = chosen.label
        out["description"] = chosen.description
        out["titles"] = chosen.titles
        if chosen.missing_langs:
            out["missing"] = [missing_message(chosen, lang) for lang in chosen.missing_langs]
    out["reason"] = why
    # Entities with no Wikipedia article anywhere cannot be analyzed; keep output compact.
    alts = [
        c for c in cands if (chosen is None or c.qid != chosen.qid) and c.sitelinks_total > 0
    ][: 6 if chosen is None else 3]
    out["candidates" if chosen is None else "alternatives"] = [
        {
            "qid": c.qid,
            "label": c.label,
            "description": c.description,
            "editions": c.sitelinks_total,
            "titles": c.titles,
        }
        for c in alts
    ]
    return out
