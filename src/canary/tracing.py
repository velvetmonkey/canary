"""LangSmith tracing and run observability.

Configures LangSmith tracing for all LLM calls and graph execution.
Provides run-level metrics tracking (token usage, latency, outcomes).
"""

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class SourceCheckMetrics:
    """Metrics for a single source check within a run."""

    celex_id: str
    label: str
    status: str = "pending"  # pending | baseline | no_change | changed | error
    started_at: float = 0.0
    duration_ms: float = 0.0
    hash: str | None = None
    change_count: int = 0
    citations_total: int = 0
    citations_verified: int = 0
    vault_path: str | None = None
    error: str | None = None


@dataclass
class RunMetrics:
    """Aggregate metrics for a complete CANARY run."""

    run_id: str
    started_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0
    sources_checked: int = 0
    changes_detected: int = 0
    baselines_stored: int = 0
    errors: int = 0
    extraction_tokens_in: int = 0
    extraction_tokens_out: int = 0
    source_checks: list[SourceCheckMetrics] = field(default_factory=list)

    def start(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._start_time = time.monotonic()

    def finish(self) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.duration_ms = (time.monotonic() - self._start_time) * 1000

    def start_source(self, celex_id: str, label: str) -> SourceCheckMetrics:
        metrics = SourceCheckMetrics(celex_id=celex_id, label=label, started_at=time.monotonic())
        self.source_checks.append(metrics)
        self.sources_checked += 1
        return metrics

    def finish_source(self, metrics: SourceCheckMetrics) -> None:
        metrics.duration_ms = (time.monotonic() - metrics.started_at) * 1000
        if metrics.status == "changed":
            self.changes_detected += 1
        elif metrics.status == "baseline":
            self.baselines_stored += 1
        elif metrics.status == "error":
            self.errors += 1

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round(self.duration_ms),
            "sources_checked": self.sources_checked,
            "changes_detected": self.changes_detected,
            "baselines_stored": self.baselines_stored,
            "errors": self.errors,
            "extraction_tokens": {
                "input": self.extraction_tokens_in,
                "output": self.extraction_tokens_out,
                "estimated_cost_usd": round(
                    self.extraction_tokens_in * 3 / 1_000_000
                    + self.extraction_tokens_out * 15 / 1_000_000,
                    4,
                ),
            },
            "sources": [
                {
                    "celex_id": s.celex_id,
                    "label": s.label,
                    "status": s.status,
                    "duration_ms": round(s.duration_ms),
                    "change_count": s.change_count,
                    "citations": f"{s.citations_verified}/{s.citations_total}"
                    if s.citations_total > 0
                    else None,
                    "vault_path": s.vault_path,
                    "error": s.error,
                }
                for s in self.source_checks
            ],
        }


def configure_langsmith(run_id: str) -> bool:
    """Configure LangSmith tracing if API key is available.

    Returns True if tracing is enabled.
    """
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
    if not api_key:
        logger.info("LangSmith tracing disabled (no LANGSMITH_API_KEY)")
        return False

    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "canary")
    os.environ.setdefault("LANGCHAIN_RUN_ID", run_id)

    # Ensure the key is available under both names
    if "LANGCHAIN_API_KEY" not in os.environ:
        os.environ["LANGCHAIN_API_KEY"] = api_key

    logger.info("LangSmith tracing enabled (project: canary, run: %s)", run_id)
    return True
