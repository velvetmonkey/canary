"""Change report generation — markdown with YAML frontmatter."""

import re
from datetime import date

from canary.analysis.models import ComplianceObjective, ExtractionResult
from canary.analysis.normalize import citation_matches
from canary.analysis.verifier import VerificationReport

# Regulatory entities to wikilink in body text
_REGULATION_ENTITIES = [
    # EU regulations
    "SFDR",
    "EU Taxonomy Regulation",
    "EU Taxonomy",
    "Taxonomy Regulation",
    "MiFID II",
    "CSRD",
    "NFRD",
    "AIFMD",
    "UCITS Directive",
    "UCITS",
    "Solvency II",
    "CRR",
    "CRD",
    "Benchmarks Regulation",
    # UK regulations
    "FSMA 2000",
    "FSMA 2023",
    "Climate Change Act 2008",
    "Environment Act 2021",
    "Companies Act 2006",
    "TCFD",
    "SDR",
    "FCA",
    "PRA",
    # International
    "Paris Agreement",
    "GHG Protocol",
    "ISSB",
    "TNFD",
]

# Match "Article N", "Article N(X)", "Article N(X)(y)" etc.
_ARTICLE_RE = re.compile(r"(?<!\[\[)(Article \d+(?:\(\d+\))*(?:\([a-z]\))*)(?![\w\]])")


def _apply_wikilinks(text: str, self_article: str | None = None) -> str:
    """Apply wikilinks to known regulatory entities and article cross-references.

    - Links article references: Article 8(1) → [[Article 8(1)]]
    - Links regulation short names: SFDR → [[SFDR]]
    - Skips self-references (the note's own article)
    - Skips text already inside wikilinks
    """
    # Link article references (skip self-links)
    def _link_article(m: re.Match) -> str:
        ref = m.group(1)
        if self_article and ref == self_article:
            return ref
        return f"[[{ref}]]"

    text = _ARTICLE_RE.sub(_link_article, text)

    # Link regulation entities (longest first to avoid partial matches)
    for entity in sorted(_REGULATION_ENTITIES, key=len, reverse=True):
        # Match whole word, not already inside [[ ]]
        pattern = re.compile(
            r"(?<!\[\[)(?<!\w)" + re.escape(entity) + r"(?!\w)(?!\]\])"
        )
        text = pattern.sub(f"[[{entity}]]", text)

    return text


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
        lines.append(_apply_wikilinks(extraction.summary))
        lines.append("")

        # Changes
        lines.append("## Changes")
        lines.append("")
        for i, change in enumerate(extraction.changes, 1):
            lines.append(f"### {i}. {change.change_type} — {change.source_section}")
            lines.append("")
            lines.append(f"**Materiality:** {change.materiality}")
            lines.append(f"**Confidence:** {change.confidence:.0%}")
            lines.append(f"**Rationale:** {_apply_wikilinks(change.materiality_rationale)}")
            lines.append("")
            if change.affected_articles:
                linked_articles = [f"[[{a}]]" for a in change.affected_articles]
                lines.append(f"**Affected articles:** {', '.join(linked_articles)}")
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

    # Apply wikilinks to body fields (skip self-article)
    who = _apply_wikilinks(objective.who, objective.article)
    what = _apply_wikilinks(objective.what, objective.article)
    where = _apply_wikilinks(objective.where, objective.article)
    quote = _apply_wikilinks(objective.verbatim_quote, objective.article)
    deadline = _apply_wikilinks(objective.deadline, objective.article) if objective.deadline else None

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
        f"**Who:** {who}",
        f"**What:** {what}",
        f"**Where:** {where}",
    ]

    if deadline:
        lines.append(f"**Deadline:** {deadline}")

    lines.extend([
        f"**Materiality:** {objective.materiality}",
        "",
        "## Legal Basis",
        "",
        f"> {quote}",
        "",
        f"*{objective.article}, {regulation_name}* [{citation_status}]",
        "",
    ])

    return "\n".join(lines)


def generate_regulation_readme(
    regulation_name: str,
    celex_id: str,
    objectives: list[ComplianceObjective],
    verified_articles: set[str],
    run_id: str,
) -> str:
    """Generate a README index note for a regulation's objectives folder."""
    today = date.today().isoformat()
    total = len(objectives)
    verified = len(verified_articles)

    lines = [
        "---",
        "type: regulation-index",
        f"regulation: {_yaml_quote(regulation_name)}",
        f"celex_id: {celex_id}",
        f"objectives: {total}",
        f"verified: {verified}",
        f"updated: {today}",
        f"canary_run_id: {run_id}",
        "---",
        "",
        f"# {regulation_name}",
        "",
        f"**{verified}/{total}** citations verified | "
        f"[EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex_id})",
        "",
        "## Obligations",
        "",
        "| Article | Title | Type | Materiality | Citation |",
        "|---------|-------|------|-------------|----------|",
    ]

    for obj in objectives:
        citation = "verified" if obj.article in verified_articles else "**UNVERIFIED**"
        lines.append(
            f"| {obj.article} | {obj.title} | {obj.obligation_type} "
            f"| {obj.materiality} | {citation} |"
        )

    lines.extend(["", "## Coverage by Type", ""])
    type_counts: dict[str, int] = {}
    for obj in objectives:
        type_counts[obj.obligation_type] = type_counts.get(obj.obligation_type, 0) + 1
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{t}**: {c}")

    lines.extend(["", "## Coverage by Materiality", ""])
    mat_counts: dict[str, int] = {}
    for obj in objectives:
        mat_counts[obj.materiality] = mat_counts.get(obj.materiality, 0) + 1
    for m in ["high", "medium", "low"]:
        if m in mat_counts:
            lines.append(f"- **{m}**: {mat_counts[m]}")

    lines.extend([
        "",
        f"*Extracted {today} by CANARY (run `{run_id}`)*",
        "",
    ])

    return "\n".join(lines)
