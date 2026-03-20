"""Tests for change report generation."""

from canary.analysis.models import ComplianceObjective, ExtractionResult, RegulatoryChange
from canary.analysis.verifier import CitationResult, VerificationReport
from canary.output.schema import (
    _yaml_quote,
    generate_change_report,
    generate_objective_note,
    generate_regulation_readme,
)


def _make_source(celex_id="32019R2088", label="SFDR L1", source_id="SFDR-L1"):
    return {"id": source_id, "celex_id": celex_id, "label": label, "fetcher": "eurlex", "priority": "critical"}


def _make_change(materiality="high", change_type="amendment", confidence=0.9):
    return RegulatoryChange(
        change_type=change_type,
        affected_articles=["Article 8(1)", "Article 9"],
        materiality=materiality,
        materiality_rationale="Expands disclosure scope significantly",
        supporting_quotes=["shall disclose sustainability risks"],
        source_section="Article 8",
        confidence=confidence,
    )


def _make_extraction(changes=None, celex_id="32019R2088"):
    if changes is None:
        changes = [_make_change()]
    return ExtractionResult(
        changes=changes,
        source_celex_id=celex_id,
        summary="Amendment to SFDR disclosure requirements",
    )


def _make_verification(all_verified=True):
    results = [CitationResult(quote="shall disclose sustainability risks", verified=all_verified, change_index=0)]
    return VerificationReport(
        results=results,
        all_verified=all_verified,
        unverified_count=0 if all_verified else 1,
    )


class TestGenerateChangeReport:
    def test_contains_yaml_frontmatter(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test-001",
        )
        assert report.startswith("---\n")
        assert "type: regulatory-change" in report
        assert "regulation: SFDR" in report
        assert "jurisdiction: EU" in report
        assert "canary_run_id: run-test-001" in report

    def test_severity_high(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction([_make_change(materiality="high")]),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "severity: high" in report

    def test_severity_medium(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction([_make_change(materiality="medium")]),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "severity: medium" in report

    def test_severity_low(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction([_make_change(materiality="low")]),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "severity: low" in report

    def test_contains_affected_articles(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "Article 8(1)" in report
        assert "Article 9" in report

    def test_contains_source_url(self):
        report = generate_change_report(
            source=_make_source(celex_id="32019R2088"),
            extraction=_make_extraction(),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "CELEX:32019R2088" in report

    def test_verified_citations_labelled(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(),
            verification=_make_verification(all_verified=True),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "[verified]" in report

    def test_unverified_citations_labelled(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(),
            verification=_make_verification(all_verified=False),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "[UNVERIFIED]" in report
        assert "Unverified citations should receive manual review" in report

    def test_no_extraction_fallback(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=None,
            verification=None,
            tags=None,
            run_id="run-test",
        )
        assert "Change detected but no structured extraction available" in report
        assert "regulation: unknown" in report

    def test_multiple_changes(self):
        changes = [
            _make_change(materiality="high", change_type="amendment"),
            _make_change(materiality="medium", change_type="new_requirement"),
        ]
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(changes),
            verification=None,
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "### 1." in report
        assert "### 2." in report
        assert "severity: high" in report  # highest wins

    def test_effective_date_included_when_present(self):
        change = _make_change()
        change.effective_date = "2026-06-01"
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction([change]),
            verification=None,
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "2026-06-01" in report

    def test_citation_verification_section(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(),
            verification=_make_verification(),
            tags={"regulation": "SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert "## Citation Verification" in report
        assert "1/1" in report


class TestYamlQuote:
    def test_plain_value_unchanged(self):
        assert _yaml_quote("SFDR") == "SFDR"

    def test_colon_gets_quoted(self):
        assert _yaml_quote("Reg (EU) 2019/2088: SFDR") == '"Reg (EU) 2019/2088: SFDR"'

    def test_hash_gets_quoted(self):
        assert _yaml_quote("Article #8") == '"Article #8"'

    def test_brackets_get_quoted(self):
        assert _yaml_quote("Article [8]") == '"Article [8]"'

    def test_embedded_quotes_escaped(self):
        result = _yaml_quote('He said "hello"')
        assert result == '"He said \\"hello\\""'


class TestYamlFrontmatterEscaping:
    def test_regulation_with_colon_is_quoted(self):
        report = generate_change_report(
            source=_make_source(),
            extraction=_make_extraction(),
            verification=_make_verification(),
            tags={"regulation": "Regulation (EU) 2019/2088: SFDR", "jurisdiction": "EU"},
            run_id="run-test",
        )
        assert 'regulation: "Regulation (EU) 2019/2088: SFDR"' in report

    def test_objective_note_smart_quote_source_verifies(self):
        """Source text with smart quotes should still verify against ASCII quote."""
        obj = ComplianceObjective(
            article="Article 8",
            title="Disclosure requirements",
            obligation_type="disclosure",
            who="financial market participants",
            what="disclose sustainability risks",
            where="in pre-contractual disclosures",
            deadline=None,
            materiality="high",
            verbatim_quote='"financial products shall disclose"',
        )
        source = "The regulation states \u201Cfinancial products shall disclose\u201D in Article 8."
        note = generate_objective_note(
            objective=obj,
            regulation_name="SFDR",
            celex_id="32019R2088",
            run_id="run-test",
            source_text=source,
        )
        assert "citation: verified" in note

    def test_objective_note_regulation_with_colon(self):
        obj = ComplianceObjective(
            article="Article 3",
            title="Sustainability risk policies",
            obligation_type="governance",
            who="financial market participants",
            what="Integrate sustainability risks in investment decisions",
            where="in internal policies",
            deadline=None,
            materiality="high",
            verbatim_quote="shall integrate sustainability risks",
        )
        note = generate_objective_note(
            objective=obj,
            regulation_name="Regulation (EU) 2019/2088: SFDR",
            celex_id="32019R2088",
            run_id="run-test",
        )
        assert 'regulation: "Regulation (EU) 2019/2088: SFDR"' in note


def _make_objective(article="Article 3(1)", title="Test obligation", obligation_type="disclosure", materiality="high"):
    return ComplianceObjective(
        article=article,
        title=title,
        obligation_type=obligation_type,
        who="financial market participants",
        what="Disclose sustainability risks",
        where="on websites",
        deadline=None,
        materiality=materiality,
        verbatim_quote="shall disclose sustainability risks",
    )


class TestGenerateRegulationReadme:
    def test_contains_frontmatter(self):
        objectives = [_make_objective()]
        readme = generate_regulation_readme("SFDR", "32019R2088", objectives, {"Article 3(1)"}, "run-001")
        assert "type: regulation-index" in readme
        assert "regulation: SFDR" in readme
        assert "celex_id: 32019R2088" in readme
        assert "objectives: 1" in readme
        assert "verified: 1" in readme
        assert "canary_run_id: run-001" in readme

    def test_obligations_table_rows(self):
        objectives = [
            _make_objective(article="Article 3", title="Risk policies"),
            _make_objective(article="Article 8", title="Transparency"),
        ]
        readme = generate_regulation_readme("SFDR", "32019R2088", objectives, set(), "run-001")
        assert "| Article 3 | Risk policies |" in readme
        assert "| Article 8 | Transparency |" in readme

    def test_verified_citation_status(self):
        objectives = [_make_objective(article="Article 3")]
        readme = generate_regulation_readme("SFDR", "32019R2088", objectives, {"Article 3"}, "run-001")
        assert "| verified |" in readme

    def test_unverified_citation_status(self):
        objectives = [_make_objective(article="Article 3")]
        readme = generate_regulation_readme("SFDR", "32019R2088", objectives, set(), "run-001")
        assert "| **UNVERIFIED** |" in readme

    def test_coverage_by_type(self):
        objectives = [
            _make_objective(obligation_type="disclosure"),
            _make_objective(article="Article 4", obligation_type="disclosure"),
            _make_objective(article="Article 5", obligation_type="governance"),
        ]
        readme = generate_regulation_readme("SFDR", "32019R2088", objectives, set(), "run-001")
        assert "- **disclosure**: 2" in readme
        assert "- **governance**: 1" in readme

    def test_coverage_by_materiality(self):
        objectives = [
            _make_objective(materiality="high"),
            _make_objective(article="Article 4", materiality="high"),
            _make_objective(article="Article 5", materiality="medium"),
            _make_objective(article="Article 6", materiality="low"),
        ]
        readme = generate_regulation_readme("SFDR", "32019R2088", objectives, set(), "run-001")
        lines = readme.split("\n")
        mat_section = "\n".join(lines[lines.index("## Coverage by Materiality"):])
        high_pos = mat_section.index("**high**")
        medium_pos = mat_section.index("**medium**")
        low_pos = mat_section.index("**low**")
        assert high_pos < medium_pos < low_pos

    def test_eurlex_link(self):
        readme = generate_regulation_readme("SFDR", "32019R2088", [], set(), "run-001")
        assert "CELEX:32019R2088" in readme

    def test_empty_objectives(self):
        readme = generate_regulation_readme("SFDR", "32019R2088", [], set(), "run-001")
        assert "objectives: 0" in readme
        assert "verified: 0" in readme
        assert "| Article |" in readme  # table header still present

    def test_regulation_name_with_colon(self):
        readme = generate_regulation_readme("Regulation (EU) 2019/2088: SFDR", "32019R2088", [], set(), "run-001")
        assert 'regulation: "Regulation (EU) 2019/2088: SFDR"' in readme
