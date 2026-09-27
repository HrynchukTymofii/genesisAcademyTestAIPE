import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fixtures.scenarios import CLI_SCENARIOS
from wiki_interest.cli import app
from wiki_interest.engine import load_run
from wiki_interest.report import check_summary_numbers, count_pdf_pages

runner = CliRunner()


def cli(args):
    res = runner.invoke(app, args)
    return res.exit_code, json.loads(res.stdout)


@pytest.fixture
def run_dir(recorded):
    code, out = cli(CLI_SCENARIOS["compare_uk"])
    assert code == 0
    return out["run_dir"]


@pytest.mark.parametrize("kind", ["indexed", "share", "raw"])
def test_chart_kinds(run_dir, kind):
    code, out = cli(["chart", run_dir, "--kind", kind])
    assert code == 0
    png = Path(out["chart"])
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_bad_chart_kind(run_dir):
    code, out = cli(["chart", run_dir, "--kind", "pie"])
    assert code == 1 and "indexed" in out["next_step"]


def test_report_is_one_page_with_cyrillic(run_dir):
    r = load_run(run_dir)["results"][0]
    summary = f"Інтерес до теми {r['topic']} спадає ({r['trend_pct_per_year']}% на рік)."
    code, out = cli(["report", run_dir, "--summary", summary, "--lang", "uk"])
    assert code == 0, out
    pdf = Path(out["report"]).read_bytes()
    assert count_pdf_pages(pdf) == 1
    assert b"DejaVuSans" in pdf  # embedded font that covers Cyrillic


def test_report_overflow_still_one_page(run_dir):
    long = "Interest is declining in both topics. " * 80
    code, out = cli(["report", run_dir, "--summary", long, "--out", "long.pdf"])
    assert code == 0
    assert count_pdf_pages(Path(out["report"]).read_bytes()) == 1
    assert "summary truncated" in " ".join(out["warnings"])


def test_report_rejects_invented_numbers(run_dir):
    code, out = cli(["report", run_dir, "--summary", "Astronomy grows 25% a year."])
    assert code == 1
    assert out["error"] == "summary_numbers_not_in_results"
    assert out["offending"] == ["25"]
    assert not (Path(run_dir) / "report.pdf").exists()


def test_guard_accepts_real_numbers_in_local_formats(run_dir):
    result = load_run(run_dir)
    r = result["results"][0]
    pct = r["trend_pct_per_year"]
    lo, hi = r["trend_ci95"]
    comma = f"{pct:.1f}".replace(".", ",")
    text = (
        f"Trend {pct}% per year (CI {lo} to {hi}), in Czech style {comma} %, "
        f"about {round(pct)}%, over {result['period']['months']} months and 3 years, 95% CI."
    )
    assert check_summary_numbers(result, text) == []
    assert check_summary_numbers(result, "It will grow 12345%.") == ["12345"]


def test_chart_warns_when_series_are_omitted(run_dir, monkeypatch):
    import wiki_interest.charts as charts

    monkeypatch.setattr(charts, "MAX_SERIES", 1)
    code, out = cli(["chart", run_dir, "--kind", "indexed"])
    assert code == 0
    assert "1 more are not drawn" in out["warnings"][0]
