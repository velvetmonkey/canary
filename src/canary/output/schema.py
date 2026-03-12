"""Change report generation — markdown with YAML frontmatter."""

from datetime import date

from canary.analysis.models import ComplianceObjective, ExtractionResult
from canary.analysis.normalize import citation_matches
from canary.analysis.verifier import VerificationReport


def _yaml_quote(value: str) -> str:
    """Quote a YAML value if it contains special characters."""
    if any(ch in value for ch in (":", "#", "[", "]", "{", "}", '"', "'", "&", "*", "?", "|", ">", "!", "%", "@", "`")):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


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

    regulation = _yaml_quote(tags['regulation']) if tags else 'unknown'
    jurisdiction = _yaml_quote(tags['jurisdiction']) if tags else 'unknown'

    lines = [
        "---",
        "type: regulatory-change",
        f"regulation: {regulation}",
        f"jurisdiction: {jurisdiction}",
        f"severity: {severity}",
        "status: unreviewed",
        f"detected: {today}",
        f"source_url: https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{source['celex_id']}",
        "affects:",
    ]
    for a in affects:
        lines.append(f"  - {_yaml_quote(a)}")
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


def generate_objective_note(
    objective: ComplianceObjective,
    regulation_name: str,
    celex_id: str,
    run_id: str,
    source_text: str | None = None,
) -> str:
    """Generate a vault note for a single compliance objective."""
    today = date.today().isoformat()

    # Verify the quote exists in source text
    citation_status = "unverified"
    if source_text:
        if citation_matches(objective.verbatim_quote, source_text):
            citation_status = "verified"

    lines = [
        "---",
        "type: compliance-objective",
        f"regulation: {_yaml_quote(regulation_name)}",
        f"celex_id: {celex_id}",
        f"article: {_yaml_quote(objective.article)}",
        f"obligation_type: {objective.obligation_type}",
        f"materiality: {objective.materiality}",
        "status: active",
        f"extracted: {today}",
        f"citation: {citation_status}",
        f"source_url: https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex_id}",
        f"canary_run_id: {run_id}",
        "---",
        "",
        f"# {objective.article} — {objective.title}",
        "",
        "## Obligation",
        "",
        f"**Who:** {objective.who}",
        f"**What:** {objective.what}",
        f"**Where:** {objective.where}",
    ]

    if objective.deadline:
        lines.append(f"**Deadline:** {objective.deadline}")

    lines.extend([
        f"**Materiality:** {objective.materiality}",
        "",
        "## Legal Basis",
        "",
        f"> {objective.verbatim_quote}",
        "",
        f"*{objective.article}, {regulation_name}* [{citation_status}]",
        "",
    ])

    return "\n".join(lines)
