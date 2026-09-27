import pytest

from wiki_analyst.errors import SpecError
from wiki_analyst.ranking import custom_ranking, parse_weights
from wiki_analyst.spec import validate_spec


def rec(lang, trend, share, views, conf):
    return {"topic": "t", "lang": lang, "trend_pct_per_year": trend,
            "share_per_million_last12": share, "median_daily_views": views, "confidence": conf}


RECORDS = [
    rec("a", 10.0, 1.0, 10, "moderate"),   # fast growth, tiny
    rec("b", -5.0, 100.0, 1000, "strong"),  # shrinking, big
    rec("c", 0.0, 10.0, 100, "weak"),
]


def test_parse_weights():
    assert parse_weights("growth=0.5, share=30") == {"growth": 0.5, "share": 30.0}
    with pytest.raises(SpecError) as exc:
        parse_weights("price=1")
    assert "growth" in exc.value.hint


def test_weights_change_the_winner():
    by_growth = custom_ranking(RECORDS, {"growth": 1})
    assert [r["lang"] for r in by_growth["ranked"]] == ["a", "c", "b"]
    by_size = custom_ranking(RECORDS, {"share": 1, "volume": 1})
    assert by_size["ranked"][0]["lang"] == "b"
    assert by_size["weights"] == {"share": 0.5, "volume": 0.5}  # normalised


def test_scores_are_explained_and_bounded():
    out = custom_ranking(RECORDS, {"growth": 3, "certainty": 1})
    top = out["ranked"][0]
    assert top["rank"] == 1 and set(top["points"]) == {"growth", "certainty"}
    assert all(0 <= r["score"] <= 100 for r in out["ranked"])
    assert top["score"] == pytest.approx(0.75 * top["points"]["growth"] + 0.25 * top["points"]["certainty"], abs=0.1)
    assert "relative" in out["method"]


def test_min_confidence_excludes_and_reports():
    out = custom_ranking(RECORDS, {"growth": 1}, min_confidence="moderate")
    assert [r["lang"] for r in out["ranked"]] == ["a", "b"]
    assert out["excluded"] == ["t [c]: confidence weak"]


def test_spec_validation_names_ranking_field():
    with pytest.raises(SpecError, match="ranking"):
        validate_spec({"topics": [{"qid": "Q1"}], "languages": ["pl"],
                       "ranking": {"weights": {"price": 1}}})
    with pytest.raises(SpecError, match="ranking.weights"):
        validate_spec({"topics": [{"qid": "Q1"}], "languages": ["pl"],
                       "ranking": {"weights": {"growth": 0}}})
