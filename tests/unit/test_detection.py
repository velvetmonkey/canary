"""Tests for change detection: hasher, differ, store."""

from canary.detection.differ import compute_diff, summarize_diff
from canary.detection.hasher import compute_hash, normalize_text
from canary.detection.store import DocumentStore


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
