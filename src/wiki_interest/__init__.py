"""wiki-interest: Wikipedia pageview trend analysis for topic and language-market decisions.

Importable library for cases the CLI and spec cannot express (see
references/library-api.md). Names are loaded lazily so the CLI starts fast.
"""

__version__ = "0.1.0"

_EXPORTS = {
    "WikimediaClient": "api",
    "Cache": "cache",
    "resolve_topic": "resolve",
    "entity_info": "resolve",
    "Period": "series",
    "parse_period": "series",
    "build_topic_series": "series",
    "indexed": "series",
    "TopicSeries": "series",
    "assess": "stats",
    "trend": "stats",
    "verdict": "stats",
    "year_over_year": "stats",
    "detect_spikes": "stats",
    "seasonality_strength": "stats",
    "AnalysisSpec": "spec",
    "validate_spec": "spec",
    "load_spec": "spec",
    "run_analysis": "engine",
    "load_run": "engine",
    "make_chart": "charts",
    "build_report": "report",
    "check_summary_numbers": "report",
    "WikiInterestError": "errors",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        from importlib import import_module

        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(f"module 'wiki_interest' has no attribute {name!r}")
