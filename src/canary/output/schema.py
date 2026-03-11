"""Change report generation — markdown with YAML frontmatter."""

from datetime import date

from canary.analysis.models import ExtractionResult
from canary.analysis.verifier import VerificationReport


def generate_change_report(
    source: dict,
    extraction: ExtractionResult | None,
    verification: VerificationReport | None,
    tags: dict | None,
    run_id: str,
) -> str:
    """Generate a markdown change report with YAML frontmatter."""
    today = date.today().isoformat()
    severity = "low"
    if extraction:
        if any(c.materiality == "high" for c in extraction.changes):
            severity = "high"
        elif any(c.materiality == "medium" for c in extraction.changes):
            severity = "medium"

    affects = []
    if extraction:
        for change in extraction.changes:
            affects.extend(change.affected_articles)
    affects = sorted(set(affects))

    lines = [
        "---",
        "type: regulatory-change",
        f"regulation: {tags['regulation'] if tags else 'unknown'}",
        f"jurisdiction: {tags['jurisdiction'] if tags else 'unknown'}",
        f"severity: {severity}",
        "status: unreviewed",
        f"detected: {today}",
        f"source_url: https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{source['celex_id']}",
        "affects:",
    ]
    for a in affects:
        lines.append(f"  - {a}")
    lines.append(f"canary_run_id: {run_id}")
    lines.append("---")
    lines.append("")

    # Title
    lines.append(f"# {source['label']} — Change Report {today}")
    lines.append("")

    # Summary
    if extraction:
        lines.append("## Summary")
        lines.append("")
        lines.append(extraction.summary)
        lines.append("")

        # Changes
        lines.append("## Changes")
        lines.append("")
        for i, change in enumerate(extraction.changes, 1):
            lines.append(f"### {i}. {change.change_type} — {change.source_section}")
            lines.append("")
            lines.append(f"**Materiality:** {change.materiality}")
            lines.append(f"**Confidence:** {change.confidence:.0%}")
            lines.append(f"**Rationale:** {change.materiality_rationale}")
            lines.append("")
            if change.affected_articles:
                lines.append(f"**Affected articles:** {', '.join(change.affected_articles)}")
                lines.append("")
            if change.effective_date:
                lines.append(f"**Effective date:** {change.effective_date}")
                lines.append("")

            lines.append("**Supporting quotes:**")
            for quote in change.supporting_quotes:
                # Check verification status
                verified = True
                if verification:
                    for r in verification.results:
                        if r.quote == quote:
                            verified = r.verified
                            break
                status = "verified" if verified else "UNVERIFIED"
                lines.append(f'> "{quote}" [{status}]')
                lines.append("")
    else:
        lines.append("## Summary")
        lines.append("")
        lines.append("Change detected but no structured extraction available.")
        lines.append("")

    # Verification summary
    if verification:
        lines.append("## Citation Verification")
        lines.append("")
        total = len(verification.results)
        verified = total - verification.unverified_count
        lines.append(f"**{verified}/{total}** citations mechanically verified.")
        if not verification.all_verified:
            lines.append("")
            lines.append("Unverified citations require manual review.")
        lines.append("")

    return "\n".join(lines)
