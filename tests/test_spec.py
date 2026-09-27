import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from fixtures.scenarios import CLI_SCENARIOS, EXAMPLES
from wiki_analyst.cli import app
from wiki_analyst.errors import SpecError
from wiki_analyst.spec import apply_overrides, load_spec, validate_spec

runner = CliRunner()


def cli(args):
    res = runner.invoke(app, args)
    return res.exit_code, json.loads(res.stdout)


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.yaml")), ids=lambda p: p.name)
def test_example_specs_are_valid(path):
    spec = load_spec(path)
    assert spec.topics and spec.languages


def test_errors_name_exact_fields():
    with pytest.raises(SpecError) as exc:
        validate_spec(
            {"topics": [{"qid": "Q1"}, {"qid": "X5"}], "languages": ["pl", "polish!"], "colour": 1}
        )
    msg = exc.value.message
    assert "topics[1].qid" in msg
    assert "languages" in msg and "polish!" in msg
    assert "colour" in msg


def test_topic_needs_a_source_and_text_excludes_qid():
    with pytest.raises(SpecError, match=r"topics\[0\]"):
        validate_spec({"topics": [{"label": "x"}], "languages": ["pl"]})
    with pytest.raises(SpecError, match="either text or qid"):
        validate_spec({"topics": [{"text": "a", "qid": "Q1"}], "languages": ["pl"]})


def test_overrides():
    data = {"topics": [{"qid": "Q1"}], "languages": ["pl"], "start": "2020-01", "end": "2024-12"}
    out = apply_overrides(data, ["languages=pl,cs,sk", "period=36m", "output.report.lang=uk"])
    assert out["languages"] == ["pl", "cs", "sk"]
    assert out["period"] == "36m" and "start" not in out and "end" not in out
    assert out["output"]["report"]["lang"] == "uk"
    with pytest.raises(SpecError):
        apply_overrides(data, ["nonsense"])


def test_default_comparisons_inferred():
    s = validate_spec({"topics": [{"qid": "Q1"}, {"qid": "Q2"}], "languages": ["pl", "cs"]})
    assert s.effective_comparisons() == ["languages", "topics"]


def test_run_spec_saves_resolved_spec_and_charts(recorded):
    code, out = cli(CLI_SCENARIOS["spec_astronomy"])
    assert code == 0, out
    assert out["command"] == "run"
    assert len(out["files"]["charts"]) == 2
    saved = yaml.safe_load(Path(out["files"]["spec"]).read_text(encoding="utf-8"))
    assert saved["topics"][0]["qid"] == "Q333" and saved["end"] == "2026-08"


def test_followup_edits_spec_via_set(recorded):
    code, out = cli(CLI_SCENARIOS["followup"])
    assert code == 0, out
    assert {r["lang"] for r in out["results"]} == {"uk", "pl"}
    assert out["period"]["months"] == 24
    assert "languages" in out["comparisons"]


def test_rerun_from_run_dir(recorded):
    _, first = cli(CLI_SCENARIOS["spec_astronomy"])
    code, again = cli(["run", first["run_dir"]])
    assert code == 0
    assert again["results"][0]["trend_pct_per_year"] == first["results"][0]["trend_pct_per_year"]


def test_needs_confirmation(recorded):
    code, out = cli(CLI_SCENARIOS["needs_confirmation"])
    assert code == 0
    assert out["status"] == "needs_confirmation"
    assert out["next_step"].startswith("Confirm with the user")


def test_missing_spec_file(env):
    code, out = cli(["run", "nope.yaml"])
    assert code == 1 and out["error"] == "spec_error"


def test_ambiguity_blocks_analysis_until_confirmed(recorded):
    code, out = cli(CLI_SCENARIOS["needs_confirmation"])
    assert out["status"] == "needs_confirmation"
    code, out = cli(CLI_SCENARIOS["astronomy_uk"])  # a substitute topic: blocked
    assert code == 1 and out["error"] == "confirmation_required"
    assert "--confirmed" in out["next_step"] and "Q2731224" in out["message"]
    code, out = cli(CLI_SCENARIOS["astronomy_uk"] + ["--confirmed", "ok"])  # no real quote
    assert code == 1 and out["error"] == "confirmation_required"
    code, out = cli(CLI_SCENARIOS["astronomy_uk"] + ["--confirmed", "use astronomy instead"])
    assert code == 0
    assert out["user_confirmation"]["user_answer"] == "use astronomy instead"
    code, out = cli(CLI_SCENARIOS["astronomy_uk"])  # cleared
    assert code == 0
