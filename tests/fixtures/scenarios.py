"""CLI invocations shared by record_fixtures.py (live, recording) and the tests (replay)."""

CLI_SCENARIOS = {
    "fasting_pl_cs": ["analyze", "--qid", "Q1666254", "--langs", "pl,cs", "--period", "24m"],
    "astronomy_uk": ["analyze", "--qid", "Q333", "--langs", "uk", "--period", "36m"],
    "compare_uk": ["compare", "--qids", "Q333,Q413", "--langs", "uk", "--period", "36m"],
    "ambiguous": ["analyze", "--topic", "mercury", "--langs", "pl"],
    "tiny_wiki": ["analyze", "--qid", "Q333", "--langs", "rue", "--period", "24m"],
}
