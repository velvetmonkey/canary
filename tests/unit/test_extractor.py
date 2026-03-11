"""Tests for LLM extractor with mocked Claude responses."""

from unittest.mock import AsyncMock, MagicMock, patch

from canary.analysis.extractor import ExtractionMetrics, extract_changes
from canary.analysis.models import ExtractionResult, RegulatoryChange


def _mock_extraction_result():
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


class TestExtractChanges:
    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_returns_extraction_and_metrics(self, mock_chat_cls):
        """Verify extract_changes returns both result and metrics."""
        mock_result = _mock_extraction_result()

        # Mock the chain: ChatAnthropic() -> .with_structured_output() -> .ainvoke()
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 1500, "output_tokens": 300}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={"parsed": mock_result, "raw": mock_raw_msg}
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        result, metrics = await extract_changes("diff text", "source text")

        assert isinstance(result, ExtractionResult)
        assert len(result.changes) == 1
        assert result.changes[0].change_type == "amendment"

        assert isinstance(metrics, ExtractionMetrics)
        assert metrics.input_tokens == 1500
        assert metrics.output_tokens == 300
        assert metrics.duration_ms > 0
        assert metrics.model == "claude-sonnet-4-6"

    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_truncates_long_source_text(self, mock_chat_cls):
        """Verify source text is truncated to 50k chars."""
        mock_result = _mock_extraction_result()

        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={"parsed": mock_result, "raw": mock_raw_msg}
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        long_source = "x" * 100_000
        await extract_changes("diff", long_source)

        # Verify the invocation happened
        call_args = mock_structured.ainvoke.call_args[0][0]
        user_msg = call_args[1]["content"]
        # Source text in prompt should be <= 50k + template overhead
        assert len(user_msg) < 60_000

    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_custom_model(self, mock_chat_cls):
        """Verify custom model parameter is passed through."""
        mock_result = _mock_extraction_result()

        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={"parsed": mock_result, "raw": mock_raw_msg}
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        _, metrics = await extract_changes("diff", "source", model="claude-opus-4-6")

        mock_chat_cls.assert_called_once_with(model="claude-opus-4-6", temperature=0, max_tokens=4096)
        assert metrics.model == "claude-opus-4-6"

    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_handles_missing_usage_metadata(self, mock_chat_cls):
        """Gracefully handle missing token usage info."""
        mock_result = _mock_extraction_result()

        mock_raw_msg = MagicMock(spec=[])  # No usage_metadata attr

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={"parsed": mock_result, "raw": mock_raw_msg}
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        _, metrics = await extract_changes("diff", "source")
        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0
