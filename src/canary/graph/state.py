"""LangGraph state definition for CANARY pipeline."""

from typing import TypedDict

from canary.analysis.models import ExtractionResult
from canary.analysis.verifier import VerificationReport


class SourceConfig(TypedDict):
    id: str
    celex_id: str
    label: str
    fetcher: str
    priority: str


class CANARYState(TypedDict, total=False):
    """State passed through the CANARY LangGraph pipeline."""

    # Input
    sources: list[SourceConfig]
    current_source: SourceConfig
    run_id: str

    # Fetch stage
    fetched_text: str | None
    is_first_run: bool

    # Detection stage
    changed: bool
    old_hash: str | None
    new_hash: str | None
    diff_text: str | None

    # Analysis stage
    extraction: ExtractionResult | None
    verification: VerificationReport | None
    tags: dict | None

    # Output
    report: str | None
    vault_path: str | None
    vault_enabled: bool
    errors: list[str]
