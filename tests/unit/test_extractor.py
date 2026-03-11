"""Tests for LLM extractor with mocked Claude responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest
from tenacity import wait_none

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
    async def test_passes_full_source_when_under_limit(self, mock_chat_cls):
        """Verify source text is NOT truncated when under the context limit."""
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

        long_source = "x" * 200_000
        await extract_changes("diff", long_source)

        # 200K chars is well under the ~680K limit, so the full text should be in the prompt
        call_args = mock_structured.ainvoke.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert len(user_msg) > 200_000

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

    @patch("canary.analysis.extractor._RETRY_WAIT", wait_none())
    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_retries_on_api_status_error(self, mock_chat_cls):
        """Verify retry on transient APIStatusError then success."""
        mock_result = _mock_extraction_result()
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_structured = AsyncMock()
        # First call raises, second succeeds
        mock_structured.ainvoke = AsyncMock(
            side_effect=[
                anthropic.APIStatusError(
                    message="overloaded",
                    response=MagicMock(status_code=529),
                    body=None,
                ),
                {"parsed": mock_result, "raw": mock_raw_msg},
            ]
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        result, metrics = await extract_changes("diff", "source")
        assert len(result.changes) == 1
        assert mock_structured.ainvoke.call_count == 2

    @patch("canary.analysis.extractor._RETRY_WAIT", wait_none())
    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_retries_on_api_connection_error(self, mock_chat_cls):
        """Verify retry on APIConnectionError then success."""
        mock_result = _mock_extraction_result()
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            side_effect=[
                anthropic.APIConnectionError(request=MagicMock()),
                {"parsed": mock_result, "raw": mock_raw_msg},
            ]
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        result, _ = await extract_changes("diff", "source")
        assert len(result.changes) == 1
        assert mock_structured.ainvoke.call_count == 2

    @patch("canary.analysis.extractor._RETRY_WAIT", wait_none())
    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_exhausted_retries_raises(self, mock_chat_cls):
        """Verify exception propagates after all retries exhausted."""
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        with pytest.raises(anthropic.APIConnectionError):
            await extract_changes("diff", "source")

        assert mock_structured.ainvoke.call_count == 3  # 3 attempts

    @patch("canary.analysis.extractor._MAX_SOURCE_CHARS", 10_000)
    @patch("canary.analysis.extractor.ChatAnthropic")
    async def test_logs_truncation_warning(self, mock_chat_cls, caplog):
        """Verify warning logged when source text exceeds context limit."""
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

        import logging
        with caplog.at_level(logging.WARNING, logger="canary.analysis.extractor"):
            await extract_changes("diff", "x" * 20_000)

        assert any("truncated" in r.message.lower() for r in caplog.records)
