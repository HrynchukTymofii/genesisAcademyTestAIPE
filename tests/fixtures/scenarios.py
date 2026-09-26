"""CLI invocations shared by record_fixtures.py (live, recording) and the tests (replay)."""

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]
EXAMPLES = SKILL_DIR / "specs" / "examples"

CLI_SCENARIOS = {
    "fasting_pl_cs": ["analyze", "--qid", "Q1666254", "--langs", "pl,cs", "--period", "24m"],
    "astronomy_uk": ["analyze", "--qid", "Q333", "--langs", "uk", "--period", "36m"],
    "compare_uk": ["compare", "--qids", "Q333,Q413", "--langs", "uk", "--period", "36m"],
    "ambiguous": ["analyze", "--topic", "mercury", "--langs", "pl"],
    "tiny_wiki": ["analyze", "--qid", "Q333", "--langs", "rue", "--period", "24m"],
    "needs_confirmation": ["resolve", "learning English", "--langs", "uk"],
    "spec_astronomy": ["run", str(EXAMPLES / "02-astronomy-uk.yaml")],
    "followup": [
        "run", str(EXAMPLES / "02-astronomy-uk.yaml"),
        "--set", "languages=uk,pl", "--set", "period=24m",
    ],
}
