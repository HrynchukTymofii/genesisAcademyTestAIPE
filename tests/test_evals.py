"""The eval grader itself, on synthetic stream-json transcripts."""

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent / "evals"))
from grade import grade_case, parse_transcript  # noqa: E402

EVALS = Path(__file__).parent / "evals"


def transcript(tmp_path, name, commands, answer):
    lines = []
    for i, (cmd, out) in enumerate(commands):
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd}}]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": out}]}})
    lines.append({"type": "result", "result": answer, "session_id": "s1"})
    p = tmp_path / f"{name}.turn1.jsonl"
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    return p


RESOLVE = ('uv run --project skill wiki-interest resolve "astronomy" --langs uk', '{"status": "resolved", "qid": "Q333"}')
ANALYZE = (
    "uv run --project skill wiki-interest analyze --qid Q333 --langs uk --period 36m",
    '{"results": [{"trend_pct_per_year": -47.1, "trend_ci95": [-53.2, -41.4], "confidence": "strong"}]}',
)


def test_prompts_file_is_well_formed():
    cases = yaml.safe_load((EVALS / "prompts.yaml").read_text(encoding="utf-8"))["cases"]
    assert 10 <= len(cases) <= 15
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(c["turns"] for c in cases)


def test_good_answer_passes(tmp_path):
    case = {"id": "x", "turns": ["Is astronomy growing in uk over 3 years?"], "expect_commands": ["Q333"]}
    p = transcript(tmp_path, "x", [RESOLVE, ANALYZE],
                   "Declining -47.1% per year (95% CI -53.2 to -41.4), confidence strong.")
    r = grade_case(case, [p], tmp_path)
    assert r["passed"], r


def test_invented_number_and_missing_resolve_fail(tmp_path):
    case = {"id": "y", "turns": ["Is astronomy growing?"]}
    p = transcript(tmp_path, "y", [ANALYZE], "It grows 25% per year, confidence strong.")
    r = grade_case(case, [p], tmp_path)
    assert r["checks"]["resolve_first"] is False
    assert r["checks"]["numbers_match"] is False and "25" in r["notes"][0]


def test_must_ask(tmp_path):
    case = {"id": "z", "turns": ["Mercury?"], "must_ask": True}
    ok = transcript(tmp_path, "z", [RESOLVE], "Do you mean the planet or the element?")
    assert grade_case(case, [ok], tmp_path)["checks"]["must_ask"] is True
    bad = transcript(tmp_path, "z2", [RESOLVE, ANALYZE], "Mercury is declining.")
    assert grade_case(case, [bad], tmp_path)["checks"]["must_ask"] is False


def test_parse_transcript_extracts_subcommands(tmp_path):
    p = transcript(tmp_path, "w", [RESOLVE, ANALYZE], "done")
    t = parse_transcript(p)
    assert [c[0] for c in t["commands"]] == ["resolve", "analyze"]
    assert t["answer"] == "done"


def test_analysing_after_ambiguity_fails(tmp_path):
    case = {"id": "a", "turns": ["learning English?"]}
    unsure = ('uv run --project s wiki-interest resolve "learning English" --langs uk',
              '{"status": "needs_confirmation", "qid": "Q2731224"}')
    p = transcript(tmp_path, "a", [unsure, ANALYZE], "Declining -47.1%, confidence strong.")
    r = grade_case(case, [p], tmp_path)
    assert r["checks"]["stopped_after_ambiguity(turn 1)"] is False
