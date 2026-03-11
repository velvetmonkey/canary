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
