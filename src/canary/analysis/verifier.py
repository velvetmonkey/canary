"""Mechanical citation verification — checks that quotes exist in source text."""

from dataclasses import dataclass

from canary.analysis.models import ExtractionResult


@dataclass
class CitationResult:
    quote: str
    verified: bool
    change_index: int


@dataclass
class VerificationReport:
    results: list[CitationResult]
    all_verified: bool
    unverified_count: int


def _normalize(text: str) -> str:
    """Collapse whitespace for fuzzy matching."""
    return " ".join(text.split()).lower()


def verify_citations(extraction: ExtractionResult, source_text: str) -> VerificationReport:
    """Check that every supporting_quote exists verbatim in the source text.

    Uses whitespace-normalized comparison (case-insensitive).
    """
    normalized_source = _normalize(source_text)
    results: list[CitationResult] = []

    for i, change in enumerate(extraction.changes):
        for quote in change.supporting_quotes:
            normalized_quote = _normalize(quote)
            verified = normalized_quote in normalized_source
            results.append(CitationResult(quote=quote, verified=verified, change_index=i))

    unverified = [r for r in results if not r.verified]
    return VerificationReport(
        results=results,
        all_verified=len(unverified) == 0,
        unverified_count=len(unverified),
    )
