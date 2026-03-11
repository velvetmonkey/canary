"""Issue tracking — collects problems during a run, writes to file, signals caller."""

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ISSUES_DIR = Path("data/issues")


@dataclass
class Issue:
    """A single problem detected during a CANARY run."""

    severity: str  # error | warning
    stage: str  # fetch | detect | extract | verify | vault | objective
    source: str  # celex_id or source label
    message: str
    detail: str | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class IssueCollector:
    """Collects issues across a run and writes them to disk."""

    run_id: str
    issues: list[Issue] = field(default_factory=list)

    def add(
        self,
        severity: str,
        stage: str,
        source: str,
        message: str,
        detail: str | None = None,
    ) -> Issue:
        issue = Issue(
            severity=severity,
            stage=stage,
            source=source,
            message=message,
            detail=detail,
        )
        self.issues.append(issue)

        log_fn = logger.error if severity == "error" else logger.warning
        log_fn("[%s] %s — %s: %s", self.run_id, stage, source, message)

        return issue

    def error(self, stage: str, source: str, message: str, detail: str | None = None) -> Issue:
        return self.add("error", stage, source, message, detail)

    def warning(self, stage: str, source: str, message: str, detail: str | None = None) -> Issue:
        return self.add("warning", stage, source, message, detail)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "total": len(self.issues),
            "errors": self.error_count,
            "warnings": self.warning_count,
            "issues": [asdict(i) for i in self.issues],
        }

    def write(self, output_dir: Path | None = None) -> Path | None:
        """Write issues to a JSON file. Returns path if issues were written."""
        if not self.issues:
            return None

        out_dir = output_dir or DEFAULT_ISSUES_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.run_id}.json"

        path.write_text(json.dumps(self.summary(), indent=2))
        logger.info("Wrote %d issues to %s", len(self.issues), path)
        return path
