"""Tests for issue tracking and collection."""

import json
from pathlib import Path

from canary.issues import Issue, IssueCollector


class TestIssue:
    def test_auto_timestamp(self):
        issue = Issue(severity="error", stage="fetch", source="32019R2088", message="timeout")
        assert issue.timestamp != ""
        assert "T" in issue.timestamp

    def test_explicit_timestamp(self):
        issue = Issue(
            severity="warning", stage="verify", source="X", message="Y", timestamp="2026-01-01"
        )
        assert issue.timestamp == "2026-01-01"


class TestIssueCollector:
    def test_empty_collector(self):
        ic = IssueCollector(run_id="test-001")
        assert not ic.has_errors
        assert not ic.has_warnings
        assert ic.error_count == 0
        assert ic.warning_count == 0

    def test_add_error(self):
        ic = IssueCollector(run_id="test-001")
        issue = ic.error("fetch", "32019R2088", "Connection refused")
        assert issue.severity == "error"
        assert issue.stage == "fetch"
        assert ic.has_errors
        assert ic.error_count == 1

    def test_add_warning(self):
        ic = IssueCollector(run_id="test-001")
        ic.warning("verify", "32019R2088", "1 unverified citation")
        assert ic.has_warnings
        assert not ic.has_errors
        assert ic.warning_count == 1

    def test_mixed_issues(self):
        ic = IssueCollector(run_id="test-001")
        ic.error("fetch", "A", "fetch failed")
        ic.warning("verify", "B", "unverified")
        ic.warning("extract", "C", "0 changes")
        assert ic.error_count == 1
        assert ic.warning_count == 2
        assert len(ic.issues) == 3

    def test_summary(self):
        ic = IssueCollector(run_id="test-001")
        ic.error("fetch", "A", "failed")
        ic.warning("verify", "B", "unverified")
        summary = ic.summary()
        assert summary["run_id"] == "test-001"
        assert summary["total"] == 2
        assert summary["errors"] == 1
        assert summary["warnings"] == 1
        assert len(summary["issues"]) == 2
        assert summary["issues"][0]["severity"] == "error"

    def test_write_creates_file(self, tmp_path: Path):
        ic = IssueCollector(run_id="test-001")
        ic.error("fetch", "A", "failed")
        path = ic.write(output_dir=tmp_path)
        assert path is not None
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["run_id"] == "test-001"
        assert data["errors"] == 1

    def test_write_returns_none_when_no_issues(self, tmp_path: Path):
        ic = IssueCollector(run_id="test-001")
        assert ic.write(output_dir=tmp_path) is None

    def test_write_filename_uses_run_id(self, tmp_path: Path):
        ic = IssueCollector(run_id="run-abc123")
        ic.warning("x", "y", "z")
        path = ic.write(output_dir=tmp_path)
        assert path is not None
        assert path.name == "run-abc123.json"

    def test_detail_field(self):
        ic = IssueCollector(run_id="test-001")
        ic.error("extract", "A", "Pydantic validation", detail="field required: 'article'")
        assert ic.issues[0].detail == "field required: 'article'"
        summary = ic.summary()
        assert summary["issues"][0]["detail"] == "field required: 'article'"
