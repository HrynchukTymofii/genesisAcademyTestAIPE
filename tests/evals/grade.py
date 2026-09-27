"""Grade eval transcripts (claude -p --output-format stream-json) against prompts.yaml.

    uv run python tests/evals/grade.py [--workdir <dir>] [--cases id1,id2]

Writes <workdir>/grades.json and prints a table. Checks are described in prompts.yaml.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_interest.report import NUM_RE, T, _parse_candidates, count_pdf_pages

HERE = Path(__file__).parent
CONF_RE = re.compile(
    r"\b(strong|moderate|weak|insufficient[_ ]data)\b|"
    + "|".join(re.escape(v.split(" (")[0]) for lang in T.values() for v in lang["conf"].values()),
    re.I,
)
ANALYSIS_CMDS = {"analyze", "compare", "run"}


# -- transcript parsing ------------------------------------------------------------------
def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


def parse_transcript(path: Path) -> dict:
    """Return {commands: [(subcommand, command, output)], answer: str}."""
    calls: dict[str, str] = {}
    commands = []
    answer = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use" and "command" in c.get("input", {}):
                    calls[c["id"]] = c["input"]["command"]
                elif c.get("type") == "text" and c.get("text", "").strip():
                    answer = c["text"]
        elif ev.get("type") == "user":
            for c in ev.get("message", {}).get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    cmd = calls.get(c.get("tool_use_id"), "")
                    m = re.search(r"wiki-interest(?:\.exe)?\s+([a-z]+)", cmd)
                    if m and m.group(1) != "help":
                        commands.append((m.group(1), cmd, _text(c.get("content"))))
        elif ev.get("type") == "result" and ev.get("result"):
            answer = ev["result"]
    return {"commands": commands, "answer": answer}


# -- checks --------------------------------------------------------------------------------
def _numbers_in_json_text(text: str) -> set[float]:
    vals: set[float] = set()
    for tok in NUM_RE.findall(text):
        vals.update(_parse_candidates(tok))
    return vals


def unsupported_numbers(answer: str, sources: list[str]) -> list[str]:
    """Numbers in the answer that appear in no tool output and no user prompt."""
    allowed: set[float] = {95.0, 100.0, 12.0}
    for s in sources:
        allowed |= _numbers_in_json_text(s)
        for m in re.finditer(r'"months":\s*(\d+)', s):  # "36 months" may be said as "3 years"
            allowed.add(int(m.group(1)) / 12)
    bad = []
    clean = re.sub(r"\S*wiki-interest-runs\S*", " ", answer)  # paths are not claims
    clean = re.sub(r"(?m)^\s*(?:\d+[.)]|#+)\s", " ", clean)  # list numbering, headings
    for tok in NUM_RE.findall(clean):
        cands = _parse_candidates(tok)
        ok = any(
            abs(c - a) <= 0.051 or (c == round(c) and a >= 1 and abs(c - round(a)) < 1e-9)
            for c in cands
            for a in allowed
        )
        if cands and not ok:
            bad.append(tok.strip())
    return bad


def grade_case(case: dict, transcripts: list[Path], workdir: Path) -> dict:
    turns = [parse_transcript(p) for p in transcripts]
    checks: dict[str, bool | None] = {}
    notes: list[str] = []
    all_cmds = [c for t in turns for c in t["commands"]]
    answer = turns[-1]["answer"] if turns else ""
    first = turns[0]["commands"] if turns else []

    if case.get("must_ask"):
        checks["must_ask"] = not any(c[0] in ANALYSIS_CMDS for c in first) and "?" in turns[0]["answer"]
    else:
        checks["resolve_first"] = bool(first) and first[0][0] == "resolve"
        analysed = any(c[0] in ANALYSIS_CMDS and '"ok": true' in c[2] for c in turns[-1]["commands"])
        if analysed:  # no analysis (e.g. no article exists) -> no label to state
            checks["confidence_label"] = bool(CONF_RE.search(answer))

    # Never analyse something else after resolve said "ask the user" (same turn).
    for i, t in enumerate(turns, start=1):
        unclear = False
        for sub, _, out in t["commands"]:
            if sub == "resolve" and re.search(r'"status":\s*"(ambiguous|needs_confirmation)"', out):
                unclear = True
            elif unclear and sub in ANALYSIS_CMDS:
                checks[f"stopped_after_ambiguity(turn {i})"] = False
                break

    sources = [c[2] for c in all_cmds] + list(case["turns"])
    bad = unsupported_numbers(answer, sources)
    checks["numbers_match"] = not bad
    if bad:
        notes.append(f"unsupported numbers: {bad[:10]}")

    reports = []
    for _, cmd, out in all_cmds:
        cd = re.match(r'\s*cd\s+(?:"([^"]+)"|(\S+))\s*(?:&&|;)', cmd)
        base = Path(cd.group(1) or cd.group(2)) if cd else workdir
        for m in re.finditer(r'"report":\s*"([^"]+\.pdf)"', out):
            p = Path(m.group(1))
            reports.append(p if p.is_absolute() else base / p)
    if reports:
        checks["one_page_pdf"] = all(
            p.exists() and count_pdf_pages(p.read_bytes()) == 1 for p in reports
        )
    if case.get("report_lang"):
        checks["report_lang"] = any(
            c[0] == "report" and re.search(rf"--lang[= ]+{case['report_lang']}\b", c[1]) and '"ok": true' in c[2]
            for c in all_cmds
        )
    for rx in case.get("expect_commands", []):
        checks[f"cmd~{rx}"] = any(re.search(rx, c[1]) for c in all_cmds)
    for rx in case.get("forbid_commands", []):
        checks[f"no cmd~{rx}"] = not any(re.search(rx, c[1]) for c in all_cmds)
    for rx in case.get("must_mention", []):
        checks[f"mention~{rx}"] = bool(re.search(rx, answer, re.I | re.S))

    return {
        "id": case["id"],
        "passed": all(v for v in checks.values() if v is not None),
        "checks": checks,
        "notes": notes,
        "commands": [c[1] for c in all_cmds],
        "manual": case.get("manual", []),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=str(Path(tempfile.gettempdir()) / "wiki-interest-evals"))
    ap.add_argument("--cases", default="")
    args = ap.parse_args(argv)
    workdir = Path(args.workdir)
    cases = yaml.safe_load((HERE / "prompts.yaml").read_text(encoding="utf-8"))["cases"]
    wanted = {c for c in args.cases.split(",") if c}
    results = []
    for case in cases:
        if wanted and case["id"] not in wanted:
            continue
        ts = sorted((workdir / "transcripts").glob(f"{case['id']}.turn*.jsonl"))
        if not ts:
            continue
        results.append(grade_case(case, ts, workdir))
    (workdir / "grades.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in results:
        failed = [k for k, v in r["checks"].items() if v is False]
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']:40s} {', '.join(failed)} {' '.join(r['notes'])}")
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} passed automatic checks; "
          "review the 'manual' items in grades.json.")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
