"""Tests for analysis models and verifier."""

import pytest
from pydantic import ValidationError

from canary.analysis.models import ExtractionResult, RegulatoryChange
from canary.analysis.verifier import verify_citations


class TestRegulatoryChangeModel:
    def test_valid_change(self):
        change = RegulatoryChange(
            change_type="amendment",
            affected_articles=["Article 8(1)"],
            materiality="high",
            materiality_rationale="Expands disclosure scope",
            supporting_quotes=["financial products shall disclose"],
            source_section="Article 8",
            confidence=0.9,
        )
        assert change.change_type == "amendment"

    def test_invalid_change_type(self):
        with pytest.raises(ValidationError):
            RegulatoryChange(
                change_type="invalid_type",
                affected_articles=["Article 8"],
                materiality="high",
                materiality_rationale="test",
                supporting_quotes=["quote"],
                source_section="Article 8",
                confidence=0.9,
            )

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            RegulatoryChange(
                change_type="amendment",
                affected_articles=["Article 8"],
                materiality="high",
                materiality_rationale="test",
                supporting_quotes=["quote"],
                source_section="Article 8",
                confidence=1.5,
            )

    def test_invalid_materiality(self):
        with pytest.raises(ValidationError):
            RegulatoryChange(
                change_type="amendment",
                affected_articles=["Article 8"],
                materiality="extreme",
                materiality_rationale="test",
                supporting_quotes=["quote"],
                source_section="Article 8",
                confidence=0.5,
            )


class TestExtractionResult:
    def test_valid_result(self):
        result = ExtractionResult(
            changes=[
                RegulatoryChange(
                    change_type="amendment",
                    affected_articles=["Article 8"],
                    materiality="high",
                    materiality_rationale="Expands scope",
                    supporting_quotes=["shall disclose"],
                    source_section="Article 8",
                    confidence=0.85,
                )
            ],
            source_celex_id="32019R2088",
            summary="Amendment to Article 8 disclosure requirements",
        )
        assert len(result.changes) == 1

    def test_empty_changes(self):
        result = ExtractionResult(
            changes=[],
            source_celex_id="32019R2088",
            summary="No changes detected",
        )
        assert len(result.changes) == 0


class TestVerifier:
    def test_verified_quote(self):
        source = "Article 8 requires financial products to disclose sustainability risks."
        extraction = ExtractionResult(
            changes=[
                RegulatoryChange(
                    change_type="amendment",
                    affected_articles=["Article 8"],
                    materiality="high",
                    materiality_rationale="Disclosure scope",
                    supporting_quotes=["financial products to disclose sustainability risks"],
                    source_section="Article 8",
                    confidence=0.9,
                )
            ],
            source_celex_id="32019R2088",
            summary="Test",
        )
        report = verify_citations(extraction, source)
        assert report.all_verified is True
        assert report.unverified_count == 0

    def test_unverified_quote(self):
        source = "Article 8 requires disclosure."
        extraction = ExtractionResult(
            changes=[
                RegulatoryChange(
                    change_type="amendment",
                    affected_articles=["Article 8"],
                    materiality="high",
                    materiality_rationale="Test",
                    supporting_quotes=["this quote does not exist in the source"],
                    source_section="Article 8",
                    confidence=0.9,
                )
            ],
            source_celex_id="32019R2088",
            summary="Test",
        )
        report = verify_citations(extraction, source)
        assert report.all_verified is False
        assert report.unverified_count == 1

    def test_whitespace_normalized_matching(self):
        source = "financial   products\n  shall   disclose"
        extraction = ExtractionResult(
            changes=[
                RegulatoryChange(
                    change_type="amendment",
                    affected_articles=["Article 8"],
                    materiality="high",
                    materiality_rationale="Test",
                    supporting_quotes=["financial products shall disclose"],
                    source_section="Article 8",
                    confidence=0.9,
                )
            ],
            source_celex_id="32019R2088",
            summary="Test",
        )
        report = verify_citations(extraction, source)
        assert report.all_verified is True

    def test_case_insensitive_matching(self):
        source = "Article 8 requires FINANCIAL PRODUCTS to disclose."
        extraction = ExtractionResult(
            changes=[
                RegulatoryChange(
                    change_type="amendment",
                    affected_articles=["Article 8"],
                    materiality="high",
                    materiality_rationale="Test",
                    supporting_quotes=["financial products to disclose"],
                    source_section="Article 8",
                    confidence=0.9,
                )
            ],
            source_celex_id="32019R2088",
            summary="Test",
        )
        report = verify_citations(extraction, source)
        assert report.all_verified is True

    def test_empty_extraction(self):
        extraction = ExtractionResult(
            changes=[], source_celex_id="32019R2088", summary="No changes"
        )
        report = verify_citations(extraction, "source text")
        assert report.all_verified is True
        assert report.unverified_count == 0
