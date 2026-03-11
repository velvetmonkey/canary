"""Pydantic models for structured regulatory change extraction."""

from pydantic import BaseModel, Field
from typing import Literal


class RegulatoryChange(BaseModel):
    """A single extracted regulatory change with citation evidence."""

    change_type: Literal["new_requirement", "amendment", "repeal", "guidance"]
    affected_articles: list[str] = Field(
        description="Article/section numbers affected (e.g. ['Article 8(1)', 'Article 9'])"
    )
    effective_date: str | None = Field(
        default=None, description="Effective date if stated in the text"
    )
    materiality: Literal["high", "medium", "low"]
    materiality_rationale: str = Field(
        description="One sentence citing document evidence for materiality assessment"
    )
    supporting_quotes: list[str] = Field(
        description="Verbatim quotes from the source document, max 3. Copy exact words.",
        max_length=3,
    )
    source_section: str = Field(
        description="Article or section number in the source document"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    """Container for all extracted changes from a document diff."""

    changes: list[RegulatoryChange]
    source_celex_id: str
    summary: str = Field(description="Brief summary of all changes detected")


class ComplianceObjective(BaseModel):
    """A single compliance obligation extracted from regulatory text."""

    article: str = Field(description="Article reference e.g. 'Article 3' or 'Article 4(1)(a)'")
    title: str = Field(description="Short title for the obligation, max 10 words")
    obligation_type: Literal["disclosure", "reporting", "governance", "process", "prohibition"]
    who: str = Field(
        description="Who must comply — e.g. 'financial market participants', 'financial advisers'"
    )
    what: str = Field(
        description="Plain-language description of what must be done, 1-3 sentences"
    )
    where: str = Field(
        description="Where/how — e.g. 'on websites', 'in pre-contractual disclosures', 'in periodic reports'"
    )
    deadline: str | None = Field(
        default=None, description="Compliance deadline if stated in text"
    )
    materiality: Literal["high", "medium", "low"] = Field(
        description="Materiality for an EU asset manager running Article 8/9 SFDR funds"
    )
    verbatim_quote: str = Field(
        description="Exact verbatim quote from the regulation that establishes this obligation"
    )


class ObjectiveExtraction(BaseModel):
    """Container for extracted compliance objectives."""

    objectives: list[ComplianceObjective]
    source_celex_id: str
    regulation_name: str = Field(description="Full regulation name e.g. 'Regulation (EU) 2019/2088 (SFDR)'")
    summary: str = Field(description="Brief summary of the regulation's scope and purpose")
