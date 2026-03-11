"""Tests for LangGraph pipeline."""

from canary.detection.store import DocumentStore
from canary.graph.graph import build_graph
from canary.graph.nodes import detect_change, set_store
from canary.graph.state import CANARYState


class TestGraphCompilation:
    def test_graph_compiles(self):
        graph = build_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        assert "fetch_source" in node_names
        assert "detect_change" in node_names
        assert "extract_obligations" in node_names
        assert "verify_citations" in node_names
        assert "output_results" in node_names


class TestDetectChangeNode:
    async def test_first_run_stores_baseline(self):
        store = DocumentStore(":memory:")
        set_store(store)

        state: CANARYState = {
            "current_source": {
                "id": "TEST",
                "celex_id": "TEST001",
                "label": "Test Document",
                "fetcher": "eurlex",
                "priority": "critical",
            },
            "fetched_text": "Article 8 requires disclosure of sustainability risks.",
            "run_id": "test-run-001",
            "errors": [],
        }

        result = await detect_change(state)
        assert result["is_first_run"] is True
        assert result["changed"] is False
        assert result["new_hash"] is not None

        # Verify stored
        row = store.get_state("TEST001")
        assert row is not None
        store.close()

    async def test_no_change_detected(self):
        store = DocumentStore(":memory:")
        set_store(store)

        text = "Article 8 requires disclosure."
        from canary.detection.hasher import compute_hash

        store.upsert_state("TEST001", compute_hash(text), text)

        state: CANARYState = {
            "current_source": {
                "id": "TEST",
                "celex_id": "TEST001",
                "label": "Test",
                "fetcher": "eurlex",
                "priority": "critical",
            },
            "fetched_text": text,
            "run_id": "test-run-002",
            "errors": [],
        }

        result = await detect_change(state)
        assert result["changed"] is False
        assert result["is_first_run"] is False
        store.close()

    async def test_change_detected(self):
        store = DocumentStore(":memory:")
        set_store(store)

        old_text = "Article 8 requires disclosure."
        from canary.detection.hasher import compute_hash

        store.upsert_state("TEST001", compute_hash(old_text), old_text)

        new_text = "Article 8 requires enhanced disclosure of PAI indicators."
        state: CANARYState = {
            "current_source": {
                "id": "TEST",
                "celex_id": "TEST001",
                "label": "Test",
                "fetcher": "eurlex",
                "priority": "critical",
            },
            "fetched_text": new_text,
            "run_id": "test-run-003",
            "errors": [],
        }

        result = await detect_change(state)
        assert result["changed"] is True
        assert result["diff_text"] is not None
        assert "PAI indicators" in result["diff_text"]
        store.close()

    async def test_none_fetched_text(self):
        store = DocumentStore(":memory:")
        set_store(store)

        state: CANARYState = {
            "current_source": {
                "id": "TEST",
                "celex_id": "TEST001",
                "label": "Test",
                "fetcher": "eurlex",
                "priority": "critical",
            },
            "fetched_text": None,
            "run_id": "test-run-004",
            "errors": [],
        }

        result = await detect_change(state)
        assert result["changed"] is False
        store.close()
