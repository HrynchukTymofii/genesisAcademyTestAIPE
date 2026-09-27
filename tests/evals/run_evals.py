"""Run the eval prompts through Claude Code with a small model, then grade them.

    uv run python tests/evals/run_evals.py                 # all cases, --model haiku
    uv run python tests/evals/run_evals.py --cases ex1-fasting-pl-cs,ambiguous-mercury

Creates <workdir> (default <system temp>/wiki-interest-evals, outside the repo) with the skill installed as
a project skill at <workdir>/.claude/skills/wiki-interest, runs each case with
`claude -p ... --model haiku --output-format stream-json --verbose` (multi-turn cases
continue the same session with --resume), saves transcripts, then runs grade.py.
Needs network (Wikimedia) and a logged-in `claude` CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).parent
SKILL_DIR = HERE.parents[1]
IGNORE = shutil.ignore_patterns(
    ".venv", "__pycache__", ".pytest_cache", "wiki-interest-runs", "tests", "*.pyc"
)
TOOLS = "Bash,PowerShell,Read,Write,Edit,Glob,Grep"
# Outside the repo, so the agent cannot stumble into the skill's source tree.
DEFAULT_WORKDIR = Path(tempfile.gettempdir()) / "wiki-interest-evals"


def install_skill(workdir: Path) -> None:
    target = workdir / ".claude" / "skills" / "wiki-interest"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SKILL_DIR, target, ignore=IGNORE)


def run_turn(claude: str, model: str, prompt: str, workdir: Path, out: Path, session: str | None, env) -> str | None:
    cmd = [claude, "-p", prompt, "--model", model, "--output-format", "stream-json",
           "--verbose", "--allowedTools", TOOLS]
    if session:
        cmd += ["--resume", session]
    with out.open("w", encoding="utf-8") as fh:
        subprocess.run(cmd, cwd=workdir, stdout=fh, stderr=subprocess.STDOUT, env=env, check=False)
    sid = session
    for line in out.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = ev.get("session_id", sid)
    return sid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    ap.add_argument("--claude", default=shutil.which("claude") or "claude")
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    (workdir / "transcripts").mkdir(parents=True, exist_ok=True)
    install_skill(workdir)
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)  # inherited from `uv run`; would confuse the skill's uv
    uv = shutil.which("uv") or os.environ.get("UV")  # `uv run` exports UV
    if uv is None:  # e.g. uv installed with `pip install --user uv`
        try:
            import uv as uv_pkg

            uv = uv_pkg.find_uv_bin()
        except (ImportError, FileNotFoundError):
            uv = None
    if uv:
        env["PATH"] = str(Path(uv).parent) + os.pathsep + env.get("PATH", "")
    # one shared environment for the installed skill copy
    env.setdefault("UV_PROJECT_ENVIRONMENT", str(workdir / ".skill-venv"))

    cases = yaml.safe_load((HERE / "prompts.yaml").read_text(encoding="utf-8"))["cases"]
    wanted = {c for c in args.cases.split(",") if c}
    for case in cases:
        if wanted and case["id"] not in wanted:
            continue
        for old in (workdir / "transcripts").glob(f"{case['id']}.turn*.jsonl"):
            old.unlink()
        # each case is a fresh conversation: drop another case's unanswered ambiguity
        (workdir / "wiki-interest-runs" / ".pending-confirmation.json").unlink(missing_ok=True)
        session = None
        for i, turn in enumerate(case["turns"], start=1):
            out = workdir / "transcripts" / f"{case['id']}.turn{i}.jsonl"
            print(f"[{case['id']}] turn {i}...", flush=True)
            if case.get("fresh_sessions"):  # simulate a new chat: no memory of earlier turns
                session = None
            session = run_turn(args.claude, args.model, turn, workdir, out, session, env)

    from grade import main as grade_main

    return grade_main(["--workdir", str(workdir)] + (["--cases", args.cases] if args.cases else []))


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
