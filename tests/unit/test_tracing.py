"""Tests for tracing and run metrics."""

import os
from unittest.mock import patch

from canary.tracing import RunMetrics, configure_langsmith


class TestRunMetrics:
    def test_start_and_finish(self):
        m = RunMetrics(run_id="test-001")
        m.start()
        m.finish()
        assert m.started_at != ""
        assert m.completed_at != ""
        assert m.duration_ms >= 0

    def test_start_source(self):
        m = RunMetrics(run_id="test-001")
        sc = m.start_source("32019R2088", "SFDR L1")
        assert sc.celex_id == "32019R2088"
        assert sc.label == "SFDR L1"
        assert sc.status == "pending"
        assert m.sources_checked == 1

    def test_finish_source_changed(self):
        m = RunMetrics(run_id="test-001")
        sc = m.start_source("32019R2088", "SFDR L1")
        sc.status = "changed"
        m.finish_source(sc)
        assert m.changes_detected == 1
        assert sc.duration_ms >= 0

    def test_finish_source_baseline(self):
        m = RunMetrics(run_id="test-001")
        sc = m.start_source("32019R2088", "SFDR L1")
        sc.status = "baseline"
        m.finish_source(sc)
        assert m.baselines_stored == 1

    def test_finish_source_error(self):
        m = RunMetrics(run_id="test-001")
        sc = m.start_source("32019R2088", "SFDR L1")
        sc.status = "error"
        m.finish_source(sc)
        assert m.errors == 1

    def test_finish_source_no_change(self):
        m = RunMetrics(run_id="test-001")
        sc = m.start_source("32019R2088", "SFDR L1")
        sc.status = "no_change"
        m.finish_source(sc)
        assert m.changes_detected == 0
        assert m.baselines_stored == 0
        assert m.errors == 0

    def test_summary(self):
        m = RunMetrics(run_id="test-001")
        m.start()
        sc = m.start_source("32019R2088", "SFDR L1")
        sc.status = "no_change"
        m.finish_source(sc)
        m.finish()

        summary = m.summary()
        assert summary["run_id"] == "test-001"
        assert summary["sources_checked"] == 1
        assert len(summary["sources"]) == 1
        assert summary["sources"][0]["status"] == "no_change"

    def test_token_tracking(self):
        m = RunMetrics(run_id="test-001")
        m.extraction_tokens_in = 1500
        m.extraction_tokens_out = 300
        summary = m.summary()
        assert summary["extraction_tokens"]["input"] == 1500
        assert summary["extraction_tokens"]["output"] == 300

    def test_multiple_sources(self):
        m = RunMetrics(run_id="test-001")
        m.start()

        sc1 = m.start_source("32019R2088", "SFDR L1")
        sc1.status = "no_change"
        m.finish_source(sc1)

        sc2 = m.start_source("32022R1288", "SFDR RTS")
        sc2.status = "changed"
        sc2.change_count = 2
        m.finish_source(sc2)

        sc3 = m.start_source("52025PC0841", "SFDR 2.0")
        sc3.status = "error"
        sc3.error = "Fetch timeout"
        m.finish_source(sc3)

        m.finish()

        assert m.sources_checked == 3
        assert m.changes_detected == 1
        assert m.errors == 1

        summary = m.summary()
        assert summary["sources"][2]["error"] == "Fetch timeout"


class TestConfigureLangsmith:
    @patch.dict(os.environ, {}, clear=True)
    def test_disabled_without_key(self):
        # Clear any existing keys
        os.environ.pop("LANGSMITH_API_KEY", None)
        os.environ.pop("LANGCHAIN_API_KEY", None)
        assert configure_langsmith("test-run") is False

    @patch.dict(os.environ, {"LANGSMITH_API_KEY": "lsv2_test123"}, clear=False)
    def test_enabled_with_key(self):
        result = configure_langsmith("test-run")
        assert result is True
        assert os.environ.get("LANGCHAIN_TRACING_V2") == "true"
        assert os.environ.get("LANGCHAIN_PROJECT") == "canary"

    @patch.dict(os.environ, {"LANGCHAIN_API_KEY": "lsv2_test456"}, clear=False)
    def test_accepts_langchain_key(self):
        os.environ.pop("LANGSMITH_API_KEY", None)
        result = configure_langsmith("test-run")
        assert result is True
