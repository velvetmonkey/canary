"""Tests for change detection: hasher, differ, store."""

import pytest

from canary.detection.differ import compute_diff, summarize_diff
from canary.detection.hasher import compute_hash, normalize_text
from canary.detection.store import SCHEMA_VERSION, DocumentStore


class TestHasher:
    def test_normalize_collapses_whitespace(self):
        assert normalize_text("  hello   world  ") == "hello world"

    def test_normalize_lowercases(self):
        assert normalize_text("Hello WORLD") == "hello world"

    def test_hash_deterministic(self):
        assert compute_hash("hello world") == compute_hash("hello world")

    def test_hash_different_for_different_text(self):
        assert compute_hash("hello") != compute_hash("world")

    def test_hash_ignores_whitespace_differences(self):
        assert compute_hash("hello  world") == compute_hash("hello world")

    def test_hash_ignores_case(self):
        assert compute_hash("Hello") == compute_hash("hello")


class TestDiffer:
    def test_no_diff_for_identical_text(self):
        diff = compute_diff("hello\nworld", "hello\nworld")
        assert len(diff) == 0

    def test_detects_addition(self):
        diff = compute_diff("line1\nline2", "line1\nline2\nline3")
        diff_text = "\n".join(diff)
        assert "+line3" in diff_text

    def test_detects_removal(self):
        diff = compute_diff("line1\nline2\nline3", "line1\nline3")
        diff_text = "\n".join(diff)
        assert "-line2" in diff_text

    def test_summarize_truncates(self):
        long_diff = [f"line {i}" for i in range(500)]
        summary = summarize_diff(long_diff, max_lines=10)
        assert "490 more lines truncated" in summary


class TestDocumentStore:
    def test_first_insert_returns_true(self):
        store = DocumentStore(":memory:")
        assert store.upsert_state("TEST001", "abc123", "some text") is True
        store.close()

    def test_same_hash_returns_false(self):
        store = DocumentStore(":memory:")
        store.upsert_state("TEST001", "abc123", "some text")
        assert store.upsert_state("TEST001", "abc123", "some text") is False
        store.close()

    def test_different_hash_returns_true(self):
        store = DocumentStore(":memory:")
        store.upsert_state("TEST001", "abc123", "some text")
        assert store.upsert_state("TEST001", "def456", "new text") is True
        store.close()

    def test_get_state_returns_none_for_unknown(self):
        store = DocumentStore(":memory:")
        assert store.get_state("UNKNOWN") is None
        store.close()

    def test_get_state_returns_row(self):
        store = DocumentStore(":memory:")
        store.upsert_state("TEST001", "abc123", "some text")
        row = store.get_state("TEST001")
        assert row is not None
        assert row["hash"] == "abc123"
        assert row["text"] == "some text"
        store.close()

    def test_log_change(self):
        store = DocumentStore(":memory:")
        store.log_change("TEST001", None, "abc123", run_id="run-001")
        logs = store.get_change_log("TEST001")
        assert len(logs) == 1
        assert logs[0]["new_hash"] == "abc123"
        assert logs[0]["canary_run_id"] == "run-001"
        store.close()

    def test_change_log_ordering(self):
        store = DocumentStore(":memory:")
        store.log_change("TEST001", None, "hash1")
        store.log_change("TEST001", "hash1", "hash2")
        logs = store.get_change_log("TEST001")
        assert len(logs) == 2
        store.close()

    def test_save_and_retrieve_run(self):
        from canary.tracing import RunMetrics

        store = DocumentStore(":memory:")
        m = RunMetrics(run_id="test-run-001")
        m.start()
        sc = m.start_source("32019R2088", "SFDR L1")
        sc.status = "no_change"
        sc.hash = "abc123"
        m.finish_source(sc)
        m.finish()

        store.save_run(m)

        runs = store.get_run_log(5)
        assert len(runs) == 1
        assert runs[0]["run_id"] == "test-run-001"
        assert runs[0]["sources_checked"] == 1
        assert runs[0]["changes_detected"] == 0

        checks = store.get_source_checks("test-run-001")
        assert len(checks) == 1
        assert checks[0]["celex_id"] == "32019R2088"
        assert checks[0]["status"] == "no_change"
        store.close()

    def test_save_run_with_multiple_sources(self):
        from canary.tracing import RunMetrics

        store = DocumentStore(":memory:")
        m = RunMetrics(run_id="test-run-002")
        m.start()

        sc1 = m.start_source("32019R2088", "SFDR L1")
        sc1.status = "changed"
        sc1.change_count = 2
        sc1.citations_total = 3
        sc1.citations_verified = 2
        m.finish_source(sc1)

        sc2 = m.start_source("32022R1288", "SFDR RTS")
        sc2.status = "error"
        sc2.error = "Timeout"
        m.finish_source(sc2)

        m.extraction_tokens_in = 5000
        m.extraction_tokens_out = 800
        m.finish()

        store.save_run(m)

        runs = store.get_run_log()
        assert runs[0]["changes_detected"] == 1
        assert runs[0]["errors"] == 1
        assert runs[0]["extraction_tokens_in"] == 5000

        checks = store.get_source_checks("test-run-002")
        assert len(checks) == 2
        assert checks[0]["citations_verified"] == 2
        assert checks[1]["error"] == "Timeout"
        store.close()

    def test_run_log_contains_summary_json(self):
        import json

        from canary.tracing import RunMetrics

        store = DocumentStore(":memory:")
        m = RunMetrics(run_id="test-run-003")
        m.start()
        m.finish()
        store.save_run(m)

        runs = store.get_run_log()
        summary = json.loads(runs[0]["summary_json"])
        assert summary["run_id"] == "test-run-003"
        store.close()

    def test_indices_exist(self):
        store = DocumentStore(":memory:")
        indices = store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        index_names = {row["name"] for row in indices}
        assert "idx_change_log_celex" in index_names
        assert "idx_source_check_run" in index_names
        assert "idx_run_log_started" in index_names
        store.close()

    def test_schema_version_stored(self):
        store = DocumentStore(":memory:")
        row = store.conn.execute("SELECT version FROM schema_version").fetchone()
        assert row["version"] == SCHEMA_VERSION
        store.close()

    def test_schema_version_mismatch_raises(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = DocumentStore(db_path)
        store.conn.execute("UPDATE schema_version SET version = 999")
        store.conn.commit()
        store.close()

        with pytest.raises(RuntimeError, match="schema version mismatch"):
            DocumentStore(db_path)

    def test_prune_deletes_old_runs(self):
        from datetime import datetime, timedelta, timezone

        from canary.tracing import RunMetrics

        store = DocumentStore(":memory:")

        # Create an old run
        m = RunMetrics(run_id="old-run")
        m.started_at = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        m.completed_at = m.started_at
        m.duration_ms = 100
        store.save_run(m)

        # Create a recent run
        m2 = RunMetrics(run_id="new-run")
        m2.start()
        m2.finish()
        store.save_run(m2)

        result = store.prune(days=90)
        assert result["runs_deleted"] == 1

        runs = store.get_run_log()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "new-run"
        store.close()

    def test_prune_with_no_old_data(self):
        from canary.tracing import RunMetrics

        store = DocumentStore(":memory:")
        m = RunMetrics(run_id="recent-run")
        m.start()
        m.finish()
        store.save_run(m)

        result = store.prune(days=90)
        assert result["runs_deleted"] == 0
        assert result["source_checks_deleted"] == 0
        store.close()
