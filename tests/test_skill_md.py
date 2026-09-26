from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[1]


def test_skill_md_frontmatter_and_length():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 150
    _, fm, _ = text.split("---", 2)
    meta = yaml.safe_load(fm)
    assert meta["name"] == "wiki-interest"
    assert "pageview" in meta["description"].lower()


def test_referenced_files_exist():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    for name in ("interpreting", "methodology", "spec-schema", "library-api", "languages"):
        assert f"references/{name}.md" in text
        assert (SKILL / "references" / f"{name}.md").exists()
