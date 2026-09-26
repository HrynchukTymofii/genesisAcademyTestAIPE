"""Analysis spec (YAML) — the single description of a request.

`analyze` and `compare` build a spec internally; `run` loads one from YAML.
Every run saves its resolved spec (QIDs and exact months filled in) so follow-ups
are: copy spec.yaml, edit one field, `run` it again. See references/spec-schema.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .errors import SpecError
from .resolve import LANG_RE, QID_RE

ChartKind = Literal["indexed", "share", "raw"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TopicSpec(_Strict):
    """One topic = one or more Wikidata entities and/or explicit articles, summed."""

    label: str | None = None
    text: str | None = None  # free text, resolved via Wikidata (must be unambiguous)
    qid: str | None = None
    qids: list[str] = Field(default_factory=list)  # several entities summed as one topic
    articles: dict[str, list[str]] = Field(default_factory=dict)  # lang -> extra titles

    @field_validator("qid")
    @classmethod
    def _qid(cls, v):
        if v is not None and not QID_RE.match(v):
            raise ValueError(f"'{v}' is not a QID like Q12345")
        return v

    @field_validator("qids")
    @classmethod
    def _qids(cls, v):
        bad = [q for q in v if not QID_RE.match(q)]
        if bad:
            raise ValueError(f"not QIDs: {bad}")
        return v

    @model_validator(mode="after")
    def _one_source(self):
        if not (self.text or self.qid or self.qids or self.articles):
            raise ValueError("give one of: text, qid, qids, articles")
        if self.text and (self.qid or self.qids):
            raise ValueError("use either text or qid/qids, not both")
        return self

    def all_qids(self) -> list[str]:
        return list(dict.fromkeys(([self.qid] if self.qid else []) + self.qids))


class ReportSpec(_Strict):
    lang: str = "en"
    summary: str | None = None  # 2-4 sentences written by the agent; numbers must come from results
    out: str = "report.pdf"
    chart: ChartKind = "indexed"


class OutputSpec(_Strict):
    charts: list[ChartKind] = Field(default_factory=lambda: ["indexed"])
    report: ReportSpec | None = None


class OptionsSpec(_Strict):
    spike_k: float = Field(5.0, gt=0)
    base_months: int | None = Field(None, ge=1, le=12)  # None: 12 if >=24 months else 3
    merge_redirects: bool = True
    min_median_daily_views: float = Field(0, ge=0)  # exclude smaller series from rankings
    n_boot: int = Field(1000, ge=0, le=10000)


class AnalysisSpec(_Strict):
    name: str | None = None
    topics: list[TopicSpec] = Field(min_length=1)
    languages: list[str] = Field(min_length=1)
    period: str = "24m"
    start: str | None = None  # YYYY-MM, overrides period
    end: str | None = None  # YYYY-MM, default: last complete month
    metric: Literal["share", "raw"] = "share"
    comparisons: list[Literal["languages", "topics"]] | None = None  # default: inferred
    output: OutputSpec = Field(default_factory=OutputSpec)
    options: OptionsSpec = Field(default_factory=OptionsSpec)

    @field_validator("languages")
    @classmethod
    def _langs(cls, v):
        out = []
        for code in v:
            c = str(code).strip().lower()
            if not LANG_RE.match(c):
                raise ValueError(f"'{code}' is not a Wikipedia language code (e.g. pl, cs, uk)")
            if c not in out:
                out.append(c)
        return out

    def effective_comparisons(self) -> list[str]:
        if self.comparisons is not None:
            return list(self.comparisons)
        out = []
        if len(self.languages) > 1:
            out.append("languages")
        if len(self.topics) > 1:
            out.append("topics")
        return out


def _field_path(loc: tuple) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += ("." if path else "") + str(part)
    return path


def validate_spec(data: dict) -> AnalysisSpec:
    """Validate a dict; errors name the exact field, e.g. ``topics[1].qid``."""
    if not isinstance(data, dict):
        raise SpecError("Spec must be a YAML mapping.", hint="See references/spec-schema.md.")
    try:
        return AnalysisSpec.model_validate(data)
    except ValidationError as exc:
        problems = [
            f"{_field_path(e['loc']) or '(root)'}: {e['msg'].removeprefix('Value error, ')}"
            for e in exc.errors()
        ]
        raise SpecError(
            "Invalid spec: " + "; ".join(problems),
            hint="Fix the named field(s); allowed fields are in references/spec-schema.md.",
            fields=problems,
        ) from None


LIST_FIELDS = {"languages", "comparisons", "output.charts"}


def apply_overrides(data: dict, overrides: list[str]) -> dict:
    """Apply ``key=value`` edits, e.g. ``period=36m``, ``languages=pl,cs,sk``,
    ``output.report.lang=uk``. List fields take comma-separated values."""
    for item in overrides:
        key, sep, raw = item.partition("=")
        key = key.strip()
        if not sep or not key:
            raise SpecError(
                f"--set '{item}' must look like key=value.",
                hint="e.g. --set period=36m --set languages=pl,cs,sk",
            )
        if key in LIST_FIELDS:
            value = [v.strip() for v in raw.split(",") if v.strip()]
        else:
            value = yaml.safe_load(raw) if raw.strip() else None
        node = data
        parts = key.split(".")
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[parts[-1]] = value
        if key == "period":  # a new period replaces explicit bounds from the saved spec
            data.pop("start", None)
            data.pop("end", None)
    return data


def read_spec_data(path: str | Path) -> dict:
    p = Path(path)
    if p.is_dir():
        p = p / "spec.yaml"
    if not p.exists():
        raise SpecError(f"Spec file not found: {p}", hint="Pass a spec.yaml path or a run dir.")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"{p} is not valid YAML: {exc}", hint="Fix the YAML syntax.") from None
    if not isinstance(data, dict):
        raise SpecError(f"{p} must contain a YAML mapping.", hint="See references/spec-schema.md.")
    return data


def load_spec(path: str | Path, overrides: list[str] | None = None) -> AnalysisSpec:
    data = read_spec_data(path)
    if overrides:
        data = apply_overrides(data, overrides)
    return validate_spec(data)


def dump_spec(spec: AnalysisSpec, path: Path) -> None:
    data = spec.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
    for t in data["topics"]:  # drop empty containers for readability
        for k in ("qids", "articles"):
            if not t.get(k):
                t.pop(k, None)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
