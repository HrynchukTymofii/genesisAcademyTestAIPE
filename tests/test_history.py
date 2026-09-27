import json

from typer.testing import CliRunner

from fixtures.scenarios import CLI_SCENARIOS
from wiki_analyst.cli import app

runner = CliRunner()


def cli(args):
    res = runner.invoke(app, args)
    return res.exit_code, json.loads(res.stdout)


def test_history_finds_runs_by_request_topic_and_language_name(recorded):
    _, a = cli(CLI_SCENARIOS["astronomy_uk"] + ["--note", "Is astronomy growing in Ukraine?"])
    _, f = cli(CLI_SCENARIOS["fasting_pl_cs"] + ["--note", "fasting Polish vs Czech"])
    assert a["request"] == "Is astronomy growing in Ukraine?"

    code, out = cli(["history", "astronomy ukrainian"])  # language by name, not code
    assert code == 0 and out["total_runs"] == 2
    assert out["matches"][0]["run_dir"] == a["run_dir"]
    assert out["matches"][0]["headline"][0].startswith("astronomy [uk]")

    _, out = cli(["history", "Q1666254"])
    assert [m["run_dir"] for m in out["matches"]] == [f["run_dir"]]

    _, out = cli(["history", "chemistry"])
    assert out["matches"] == [] and "No earlier analysis" in out["next_step"]


def test_history_without_query_lists_newest_first(recorded):
    _, a = cli(CLI_SCENARIOS["astronomy_uk"])
    _, b = cli(CLI_SCENARIOS["compare_uk"])
    _, out = cli(["history"])
    assert out["matches"][0]["run_dir"] == b["run_dir"]


def test_history_run_reprints_saved_numbers(recorded):
    _, a = cli(CLI_SCENARIOS["astronomy_uk"])
    code, out = cli(["history", "--run", a["run_dir"]])
    assert code == 0
    assert out["results"][0]["trend_pct_per_year"] == a["results"][0]["trend_pct_per_year"]
    assert "details" not in out  # compact, like the original output


def test_history_bad_run_dir(env):
    code, out = cli(["history", "--run", "nowhere"])
    assert code == 1 and "history" in out["next_step"]
