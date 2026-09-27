"""Errors carry an actionable ``hint`` so a small model knows what to do next."""

from __future__ import annotations


class WikiInterestError(Exception):
    """Base error. ``code`` is a stable machine-readable identifier."""

    code = "error"

    def __init__(self, message: str, hint: str | None = None, **details):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details

    def to_dict(self) -> dict:
        out = {"ok": False, "error": self.code, "message": self.message}
        if self.hint:
            out["next_step"] = self.hint
        out.update({k: v for k, v in self.details.items() if v is not None})
        return out


class ApiError(WikiInterestError):
    code = "api_error"


class ResolveError(WikiInterestError):
    code = "resolve_error"


class AmbiguousTopicError(WikiInterestError):
    code = "ambiguous_topic"


class MissingArticleError(WikiInterestError):
    code = "missing_article"


class SpecError(WikiInterestError):
    code = "spec_error"


class DataError(WikiInterestError):
    code = "data_error"


class SummaryGuardError(WikiInterestError):
    code = "summary_numbers_not_in_results"


class ConfirmationRequired(WikiInterestError):
    code = "confirmation_required"
