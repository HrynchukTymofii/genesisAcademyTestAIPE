import pytest

from wiki_analyst.errors import ResolveError
from wiki_analyst.resolve import entity_info, missing_message, resolve_topic, validate_langs


def test_validate_langs():
    assert validate_langs(["PL", " cs", "pl", "be-tarask"]) == ["pl", "cs", "be-tarask"]
    with pytest.raises(ResolveError):
        validate_langs(["polish!"])


def test_resolves_dominant_exact_match(client):
    out = resolve_topic(client, "astronomy", ["uk"])
    assert out["status"] == "resolved"
    assert out["qid"] == "Q333"
    assert out["titles"]["uk"] == "Астрономія"
    assert all(a["qid"] != "Q333" for a in out["alternatives"])


def test_ambiguous_topic_returns_candidates(client):
    out = resolve_topic(client, "mercury", ["pl"])
    assert out["status"] == "ambiguous"
    qids = [c["qid"] for c in out["candidates"]]
    assert "Q308" in qids and "Q925" in qids  # planet and element
    assert "qid" not in out  # nothing silently chosen


def test_missing_language_is_reported(client):
    out = resolve_topic(client, "intermittent fasting", ["pl", "cs"])
    assert out["status"] == "resolved"
    assert out["titles"]["cs"] == "Přerušovaný půst"
    assert out["titles"]["pl"] is None
    assert out["missing"][0].startswith("No pl article for Q1666254")
    assert "Available:" in out["missing"][0]


def test_entity_info_and_missing_message(client):
    ent = entity_info(client, ["Q1666254"], ["pl", "cs"])["Q1666254"]
    assert ent.missing_langs == ["pl"]
    assert ent.domains["cs"] == "cs.wikipedia.org"
    msg = missing_message(ent, "pl")
    assert "cs" in msg and "en" in msg


def test_bad_qid(client):
    with pytest.raises(ResolveError):
        entity_info(client, ["not-a-qid"], ["pl"])
