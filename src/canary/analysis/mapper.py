"""Compliance mapping stub — tags changes with regulation and jurisdiction.

Full compliance matrix mapping deferred to Phase 2 (RAG over existing obligations).
"""

from canary.analysis.models import ExtractionResult


def tag_changes(extraction: ExtractionResult, regulation: str, jurisdiction: str) -> dict:
    """Tag extraction result with regulation metadata."""
    return {
        "regulation": regulation,
        "jurisdiction": jurisdiction,
        "celex_id": extraction.source_celex_id,
        "change_count": len(extraction.changes),
        "high_materiality_count": sum(
            1 for c in extraction.changes if c.materiality == "high"
        ),
    }
