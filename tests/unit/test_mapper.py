"""Tests for compliance mapper."""

from canary.analysis.mapper import tag_changes
from canary.analysis.models import ExtractionResult, RegulatoryChange


def _make_extraction(materialities=None):
    if materialities is None:
        materialities = ["high"]
    changes = [
        RegulatoryChange(
            change_type="amendment",
            affected_articles=["Article 8"],
            materiality=m,
            materiality_rationale="test",
            supporting_quotes=["quote"],
            source_section="Article 8",
            confidence=0.9,
        )
        for m in materialities
    ]
    return ExtractionResult(
        changes=changes, source_celex_id="32019R2088", summary="Test"
    )


class TestTagChanges:
    def test_tags_regulation_and_jurisdiction(self):
        tags = tag_changes(_make_extraction(), regulation="SFDR", jurisdiction="EU")
        assert tags["regulation"] == "SFDR"
        assert tags["jurisdiction"] == "EU"

    def test_counts_changes(self):
        tags = tag_changes(
            _make_extraction(["high", "medium", "low"]),
            regulation="SFDR",
            jurisdiction="EU",
        )
        assert tags["change_count"] == 3

    def test_counts_high_materiality(self):
        tags = tag_changes(
            _make_extraction(["high", "medium", "high"]),
            regulation="SFDR",
            jurisdiction="EU",
        )
        assert tags["high_materiality_count"] == 2

    def test_zero_high_materiality(self):
        tags = tag_changes(
            _make_extraction(["low", "medium"]),
            regulation="SFDR",
            jurisdiction="EU",
        )
        assert tags["high_materiality_count"] == 0

    def test_includes_celex_id(self):
        tags = tag_changes(_make_extraction(), regulation="SFDR", jurisdiction="EU")
        assert tags["celex_id"] == "32019R2088"

    def test_empty_changes(self):
        extraction = ExtractionResult(
            changes=[], source_celex_id="32019R2088", summary="No changes"
        )
        tags = tag_changes(extraction, regulation="SFDR", jurisdiction="EU")
        assert tags["change_count"] == 0
        assert tags["high_materiality_count"] == 0
