"""Mechanical citation verification — checks that quotes exist in source text."""

from dataclasses import dataclass

from canary.analysis.models import ExtractionResult
from canary.analysis.normalize import citation_matches


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


def verify_citations(extraction: ExtractionResult, source_text: str) -> VerificationReport:
    """Check that every supporting_quote exists verbatim in the source text.

    Uses whitespace-normalized comparison (case-insensitive).
    """
    results: list[CitationResult] = []

    for i, change in enumerate(extraction.changes):
        for quote in change.supporting_quotes:
            verified = citation_matches(quote, source_text)
            results.append(CitationResult(quote=quote, verified=verified, change_index=i))

    unverified = [r for r in results if not r.verified]
    return VerificationReport(
        results=results,
        all_verified=len(unverified) == 0,
        unverified_count=len(unverified),
    )
