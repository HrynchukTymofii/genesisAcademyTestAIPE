"""CLI JSON contract, replayed from recorded API fixtures (no network)."""

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from fixtures.scenarios import CLI_SCENARIOS
from wiki_analyst.cli import app

runner = CliRunner()


def invoke(name_or_args):
    args = CLI_SCENARIOS[name_or_args] if isinstance(name_or_args, str) else name_or_args
    res = runner.invoke(app, args)
    return res.exit_code, json.loads(res.stdout)


def test_analyze_missing_language_and_run_dir(recorded):
    code, out = invoke("fasting_pl_cs")
    assert code == 0 and out["ok"]
    assert [r["lang"] for r in out["results"]] == ["cs"]
    miss = out["missing"][0]
    assert miss["lang"] == "pl" and miss["message"].startswith("No pl article for Q1666254")
    assert miss["search_suggestions"]  # unverified candidates for the agent to confirm
    run = Path(out["run_dir"])
    assert (run / "result.json").exists() and (run / "spec.yaml").exists()
    assert (run / "series" / "intermittent-fasting_cs_monthly.csv").exists()
    spec = yaml.safe_load((run / "spec.yaml").read_text(encoding="utf-8"))
    assert spec["topics"][0]["qid"] == "Q1666254"
    assert spec["end"] == "2026-08"


def test_analyze_record_contract(recorded):
    code, out = invoke("astronomy_uk")
    assert code == 0
    r = out["results"][0]
    for key in (
        "verdict", "confidence", "trend_pct_per_year", "trend_ci95", "mann_kendall_p",
        "yoy_pct", "median_daily_views", "share_per_million_last12", "reasons", "warnings",
    ):
        assert key in r
    assert r["confidence"] in ("strong", "moderate", "weak", "insufficient_data")
    assert out["period"] == {"start": "2023-09", "end": "2026-08", "months": 36}
    assert out["headline"][0].startswith("astronomy [uk]: ")
    assert f"{r['trend_pct_per_year']:+.1f}%/yr" in out["headline"][0]


def test_output_is_compact(recorded):
    _, out = invoke("astronomy_uk")
    text = json.dumps(out)
    assert len(text) < 6000
    assert "details" not in out  # full-precision stats stay in result.json

    def longest_list(o):
        if isinstance(o, list):
            return max([len(o), *(longest_list(x) for x in o)])
        if isinstance(o, dict):
            return max([0, *(longest_list(v) for v in o.values())])
        return 0

    assert longest_list(out) < 12  # no raw time series on stdout


def test_compare_ranks_topics(recorded):
    code, out = invoke("compare_uk")
    assert code == 0
    ranking = out["comparisons"]["topics"][0]["ranked_by_trend"]
    assert {x["topic"] for x in ranking} == {"astronomy", "physics"}
    trends = [x["trend_pct_per_year"] for x in ranking]
    assert trends == sorted(trends, reverse=True)


def test_ambiguous_topic_is_an_actionable_error(recorded):
    code, out = invoke("ambiguous")
    assert code == 1 and out["ok"] is False
    assert out["error"] == "ambiguous_topic"
    assert {"Q308", "Q925"} <= {c["qid"] for c in out["candidates"]}
    assert "--qid" in out["next_step"]


def test_tiny_wiki(recorded):
    code, out = invoke("tiny_wiki")
    assert code == 0
    r = out["results"][0]
    assert r["confidence"] in ("weak", "insufficient_data")


def test_invalid_language_names_field(env):
    code, out = invoke(["analyze", "--qid", "Q333", "--langs", "polish!"])
    assert code == 1
    assert out["error"] == "spec_error"
    assert "languages[0]" in out["message"] or "languages" in out["message"]


def test_bad_period(env):
    code, out = invoke(["analyze", "--qid", "Q333", "--langs", "uk", "--period", "forever"])
    assert code == 1 and "period" in out["message"]


def test_min_daily_views_excludes_small_series_from_rankings(recorded):
    code, out = invoke(CLI_SCENARIOS["compare_uk"] + ["--min-daily-views", "100000"])
    assert code == 0
    assert "topics" not in out["comparisons"]  # nothing big enough to rank
    assert len(out["comparisons"]["excluded_from_rankings"]) == 2
    code, out = invoke(CLI_SCENARIOS["compare_uk"] + ["--min-daily-views", "1"])
    assert len(out["comparisons"]["topics"][0]["ranked_by_trend"]) == 2


def test_overall_ranking_and_relative_to_edition(recorded):
    code, out = invoke("compare_uk_pl")
    assert code == 0
    overall = out["comparisons"]["overall_ranked_by_trend"]
    assert len(overall) == 4
    trends = [x["trend_pct_per_year"] for x in overall]
    assert trends == sorted(trends, reverse=True)  # the model never sorts itself
    for r in out["results"]:
        assert r["relative_to_edition"].endswith(f"{r['lang']} Wikipedia overall")
        if r["verdict"] == "declining":
            assert r["relative_to_edition"].startswith("losing ground")


def test_single_language_has_no_overall_ranking(recorded):
    _, out = invoke("compare_uk")
    assert "overall_ranked_by_trend" not in out["comparisons"]


def test_rank_by_cli(recorded):
    code, out = invoke(CLI_SCENARIOS["compare_uk_pl"] + ["--rank-by", "growth=0.7,share=0.3"])
    assert code == 0
    cr = out["comparisons"]["custom_ranking"]
    assert len(cr["ranked"]) == 4 and cr["ranked"][0]["rank"] == 1
    scores = [r["score"] for r in cr["ranked"]]
    assert scores == sorted(scores, reverse=True)
    code, out = invoke(CLI_SCENARIOS["compare_uk_pl"] + ["--rank-by", "price=1"])
    assert code == 1 and out["error"] == "spec_error"


def test_every_result_cites_checkable_sources(recorded):
    from pathlib import Path

    _, out = invoke("astronomy_uk")
    src = out["results"][0]["sources"]
    assert src["wikipedia"] == [
        "https://uk.wikipedia.org/wiki/%D0%90%D1%81%D1%82%D1%80%D0%BE%D0%BD%D0%BE%D0%BC%D1%96%D1%8F"
    ]
    assert src["wikidata"] == ["https://www.wikidata.org/wiki/Q333"]
    pv = src["pageviews"]
    assert pv.startswith("https://pageviews.wmcloud.org/?") and "project=uk.wikipedia.org" in pv
    assert "start=2023-09-01" in pv and "end=2026-08-31" in pv and "agent=user" in pv
    assert "redirects=1" in pv  # redirects are merged, so the public page must merge them too
    assert src["edition_total"].startswith("https://pageviews.wmcloud.org/siteviews/?")
    assert "sites=uk.wikipedia.org" in src["edition_total"]
    assert Path(src["data_file"]).exists()
