"""End-to-end graph tests with simulated document changes."""

from unittest.mock import AsyncMock, patch

from canary.analysis.models import ExtractionResult, RegulatoryChange
from canary.detection.store import DocumentStore
from canary.graph.graph import build_graph
from canary.graph.nodes import set_fetcher, set_store, set_vault_writer
from canary.graph.state import CANARYState


def _make_source():
    return {
        "id": "SFDR-L1",
        "celex_id": "32019R2088",
        "label": "SFDR Level 1",
        "fetcher": "eurlex",
        "priority": "critical",
    }


def _mock_extraction():
    return ExtractionResult(
        changes=[
            RegulatoryChange(
                change_type="amendment",
                affected_articles=["Article 8(1)"],
                materiality="high",
                materiality_rationale="Expands disclosure scope",
                supporting_quotes=["shall disclose sustainability risks"],
                source_section="Article 8",
                confidence=0.92,
            )
        ],
        source_celex_id="32019R2088",
        summary="Amendment to Article 8 disclosure requirements",
    )


class TestGraphE2EFirstRun:
    """Test the full pipeline on first run (baseline storage, no extraction)."""

    async def test_first_run_stores_baseline(self):
        store = DocumentStore(":memory:")
        set_store(store)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_text = AsyncMock(
            return_value=("Article 8 requires disclosure of sustainability risks.", True)
        )
        set_fetcher(mock_fetcher)
        set_vault_writer(None)

        graph = build_graph()

        state: CANARYState = {
            "current_source": _make_source(),
            "run_id": "test-first-run",
            "vault_enabled": False,
            "errors": [],
        }

        result = await graph.ainvoke(state)

        assert result["is_first_run"] is True
        assert result["changed"] is False
        assert result["new_hash"] is not None

        # Verify stored in DB
        row = store.get_state("32019R2088")
        assert row is not None
        store.close()


class TestGraphE2ENoChange:
    """Test the full pipeline when document hasn't changed."""

    async def test_no_change_skips_extraction(self):
        store = DocumentStore(":memory:")
        text = "Article 8 requires disclosure."
        from canary.detection.hasher import compute_hash

        store.upsert_state("32019R2088", compute_hash(text), text)
        set_store(store)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_text = AsyncMock(return_value=(text, True))
        set_fetcher(mock_fetcher)
        set_vault_writer(None)

        graph = build_graph()

        state: CANARYState = {
            "current_source": _make_source(),
            "run_id": "test-no-change",
            "vault_enabled": False,
            "errors": [],
        }

        result = await graph.ainvoke(state)

        assert result["changed"] is False
        assert result.get("extraction") is None
        store.close()


class TestGraphE2EWithChange:
    """Test the full pipeline when a document change is detected."""

    @patch("canary.graph.nodes.extract_changes")
    async def test_change_triggers_full_pipeline(self, mock_extract):
        """Simulated change: store old text, fetch new text, verify extraction runs."""
        from canary.analysis.extractor import ExtractionMetrics

        mock_extraction = _mock_extraction()
        mock_metrics = ExtractionMetrics(
            model="claude-sonnet-4-6", duration_ms=1500, input_tokens=2000, output_tokens=400
        )
        mock_extract.return_value = (mock_extraction, mock_metrics)

        store = DocumentStore(":memory:")
        old_text = "Article 8 requires disclosure."
        new_text = "Article 8 requires enhanced disclosure of PAI indicators and sustainability risks."
        from canary.detection.hasher import compute_hash

        store.upsert_state("32019R2088", compute_hash(old_text), old_text)
        set_store(store)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_text = AsyncMock(return_value=(new_text, True))
        set_fetcher(mock_fetcher)
        set_vault_writer(None)

        graph = build_graph()

        state: CANARYState = {
            "current_source": _make_source(),
            "run_id": "test-with-change",
            "vault_enabled": False,
            "errors": [],
        }

        result = await graph.ainvoke(state)

        # Change detected
        assert result["changed"] is True
        assert result["diff_text"] is not None
        assert "PAI indicators" in result["diff_text"]

        # Extraction ran
        mock_extract.assert_called_once()
        assert result["extraction"] is not None
        assert len(result["extraction"].changes) == 1

        # Verification ran
        assert result["verification"] is not None

        # Report generated
        assert result["report"] is not None
        assert "Article 8" in result["report"]

        # Token metrics passed through
        assert result.get("extraction_metrics") is not None
        assert result["extraction_metrics"].input_tokens == 2000

        store.close()

    @patch("canary.graph.nodes.extract_changes")
    async def test_change_with_unverified_citation(self, mock_extract):
        """Extraction with a quote not in the source text — verifier should flag it."""
        from canary.analysis.extractor import ExtractionMetrics

        extraction = ExtractionResult(
            changes=[
                RegulatoryChange(
                    change_type="amendment",
                    affected_articles=["Article 8"],
                    materiality="high",
                    materiality_rationale="test",
                    supporting_quotes=["this quote does not exist in the document"],
                    source_section="Article 8",
                    confidence=0.7,
                )
            ],
            source_celex_id="32019R2088",
            summary="Test with bad citation",
        )
        mock_metrics = ExtractionMetrics(
            model="claude-sonnet-4-6", duration_ms=1000, input_tokens=1000, output_tokens=200
        )
        mock_extract.return_value = (extraction, mock_metrics)

        store = DocumentStore(":memory:")
        old_text = "Original text."
        new_text = "Updated Article 8 requirements for disclosure."
        from canary.detection.hasher import compute_hash

        store.upsert_state("32019R2088", compute_hash(old_text), old_text)
        set_store(store)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_text = AsyncMock(return_value=(new_text, True))
        set_fetcher(mock_fetcher)
        set_vault_writer(None)

        graph = build_graph()

        state: CANARYState = {
            "current_source": _make_source(),
            "run_id": "test-bad-citation",
            "vault_enabled": False,
            "errors": [],
        }

        result = await graph.ainvoke(state)

        assert result["verification"] is not None
        assert result["verification"].all_verified is False
        assert result["verification"].unverified_count == 1
        assert "UNVERIFIED" in result["report"]

        store.close()

    async def test_fetch_error_handled_gracefully(self):
        """Fetch failure should not crash the pipeline."""
        store = DocumentStore(":memory:")
        set_store(store)

        mock_fetcher = AsyncMock()
        mock_fetcher.fetch_text = AsyncMock(side_effect=Exception("Connection refused"))
        set_fetcher(mock_fetcher)
        set_vault_writer(None)

        graph = build_graph()

        state: CANARYState = {
            "current_source": _make_source(),
            "run_id": "test-fetch-error",
            "vault_enabled": False,
            "errors": [],
        }

        result = await graph.ainvoke(state)

        assert result["changed"] is False
        assert any("Fetch error" in e for e in result.get("errors", []))
        store.close()
