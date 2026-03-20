"""Tests for objective extraction, including chunked extraction for large documents."""

from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest
from tenacity import wait_none

from canary.analysis.models import ComplianceObjective, ObjectiveExtraction
from canary.analysis.objectives import (
    ObjectiveMetrics,
    RequoteResult,
    _split_chunks,
    extract_objectives,
    requote_citations,
)


def _mock_objective(article="Article 3(1)", title="Test obligation"):
    return ComplianceObjective(
        article=article,
        title=title,
        obligation_type="disclosure",
        who="financial market participants",
        what="Disclose sustainability risks",
        where="on websites",
        deadline=None,
        materiality="high",
        verbatim_quote="shall disclose sustainability risks",
    )


def _mock_extraction(articles=None):
    if articles is None:
        articles = ["Article 3(1)"]
    return ObjectiveExtraction(
        objectives=[_mock_objective(article=a) for a in articles],
        source_celex_id="32019R2088",
        regulation_name="SFDR",
        summary="Test extraction",
    )


class TestSplitChunks:
    def test_small_text_returns_single_chunk(self):
        chunks = _split_chunks("hello world", max_chars=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == "hello world"

    def test_splits_large_text(self):
        # 10K chars, 3K max per chunk, 500 overlap
        text = "a" * 10_000
        chunks = _split_chunks(text, max_chars=3_000, overlap=500)
        assert len(chunks) >= 3
        # Every chunk is within limits
        for chunk in chunks:
            assert len(chunk) <= 3_000

    def test_overlap_between_chunks(self):
        text = "AAAA\n\nBBBB\n\nCCCC\n\nDDDD\n\nEEEE"
        chunks = _split_chunks(text, max_chars=15, overlap=5)
        assert len(chunks) >= 2
        # The end of one chunk should overlap with the start of the next
        for i in range(len(chunks) - 1):
            tail = chunks[i][-5:]
            assert tail in chunks[i + 1]

    def test_prefers_paragraph_breaks(self):
        text = "First paragraph content.\n\nSecond paragraph content.\n\nThird paragraph."
        chunks = _split_chunks(text, max_chars=40, overlap=5)
        # Should break at \n\n boundaries when possible
        assert len(chunks) >= 2


class TestExtractObjectivesSinglePass:
    @patch("canary.analysis.objectives._extract_single")
    async def test_small_doc_single_pass(self, mock_extract):
        """Documents under the limit use a single extraction call."""
        mock_extract.return_value = (
            _mock_extraction(["Article 3(1)", "Article 4(1)"]),
            ObjectiveMetrics(
                model="claude-sonnet-4-6", duration_ms=100,
                input_tokens=100, output_tokens=50, objectives_extracted=2,
            ),
        )

        result, metrics = await extract_objectives("short text", count=10)
        assert len(result.objectives) == 2
        assert metrics.chunks == 1
        mock_extract.assert_called_once()


class TestExtractObjectivesChunked:
    @patch("canary.analysis.objectives._MAX_SOURCE_CHARS", 100)
    @patch("canary.analysis.objectives._CHUNK_OVERLAP_CHARS", 20)
    @patch("canary.analysis.objectives._extract_single")
    async def test_large_doc_splits_into_chunks(self, mock_extract):
        """Documents over the limit are split and merged."""
        # 200 chars with max=100, overlap=20 → 3 chunks
        # Chunk 1: articles 3, 4; Chunk 2: articles 4 (dup), 5; Chunk 3: article 6
        mock_extract.side_effect = [
            (
                _mock_extraction(["Article 3(1)", "Article 4(1)"]),
                ObjectiveMetrics(
                    model="claude-sonnet-4-6", duration_ms=100,
                    input_tokens=100, output_tokens=50, objectives_extracted=2,
                ),
            ),
            (
                _mock_extraction(["Article 4(1)", "Article 5(1)"]),
                ObjectiveMetrics(
                    model="claude-sonnet-4-6", duration_ms=100,
                    input_tokens=100, output_tokens=50, objectives_extracted=2,
                ),
            ),
            (
                _mock_extraction(["Article 6(1)"]),
                ObjectiveMetrics(
                    model="claude-sonnet-4-6", duration_ms=50,
                    input_tokens=50, output_tokens=25, objectives_extracted=1,
                ),
            ),
        ]

        # 200 chars > 100 limit → will chunk
        result, metrics = await extract_objectives("x" * 200, count=10)

        # Article 4(1) should be deduplicated
        articles = [o.article for o in result.objectives]
        assert "Article 3(1)" in articles
        assert "Article 4(1)" in articles
        assert "Article 5(1)" in articles
        assert "Article 6(1)" in articles
        assert len(result.objectives) == 4  # 5 total, 1 deduped

        # Aggregate metrics
        assert metrics.chunks == 3
        assert metrics.input_tokens == 250  # 100 + 100 + 50
        assert metrics.output_tokens == 125  # 50 + 50 + 25

    @patch("canary.analysis.objectives._MAX_SOURCE_CHARS", 100)
    @patch("canary.analysis.objectives._CHUNK_OVERLAP_CHARS", 20)
    @patch("canary.analysis.objectives._extract_single")
    async def test_dedup_preserves_first_occurrence(self, mock_extract):
        """When an article appears in multiple chunks, keep the first occurrence."""
        obj_first = _mock_objective(article="Article 8(1)", title="First version")
        obj_second = _mock_objective(article="Article 8(1)", title="Second version")
        obj_third = _mock_objective(article="Article 8(1)", title="Third version")

        def _metrics():
            return ObjectiveMetrics(
                model="m", duration_ms=50,
                input_tokens=50, output_tokens=25, objectives_extracted=1,
            )

        mock_extract.side_effect = [
            (
                ObjectiveExtraction(
                    objectives=[obj_first],
                    source_celex_id="32019R2088",
                    regulation_name="SFDR",
                    summary="Chunk 1",
                ),
                _metrics(),
            ),
            (
                ObjectiveExtraction(
                    objectives=[obj_second],
                    source_celex_id="32019R2088",
                    regulation_name="SFDR",
                    summary="Chunk 2",
                ),
                _metrics(),
            ),
            (
                ObjectiveExtraction(
                    objectives=[obj_third],
                    source_celex_id="32019R2088",
                    regulation_name="SFDR",
                    summary="Chunk 3",
                ),
                _metrics(),
            ),
        ]

        result, _ = await extract_objectives("x" * 200, count=10)
        assert len(result.objectives) == 1
        assert result.objectives[0].title == "First version"


class TestRequoteCitations:
    @patch("canary.analysis.objectives._RETRY_WAIT", wait_none())
    @patch("canary.analysis.objectives.ChatAnthropic")
    async def test_returns_corrected_objectives(self, mock_chat_cls):
        corrected = _mock_objective(article="Article 3(1)", title="Corrected")
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 500, "output_tokens": 200}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={
                "parsed": RequoteResult(corrections=[corrected]),
                "raw": mock_raw_msg,
            }
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        originals = [_mock_objective()]
        results, metrics = await requote_citations(originals, "source text")

        assert len(results) == 1
        assert results[0].title == "Corrected"

    @patch("canary.analysis.objectives._RETRY_WAIT", wait_none())
    @patch("canary.analysis.objectives.ChatAnthropic")
    async def test_metrics_tracked(self, mock_chat_cls):
        corrected = _mock_objective()
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 800, "output_tokens": 300}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={
                "parsed": RequoteResult(corrections=[corrected]),
                "raw": mock_raw_msg,
            }
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        _, metrics = await requote_citations([_mock_objective()], "source text")
        assert metrics.input_tokens == 800
        assert metrics.output_tokens == 300
        assert metrics.duration_ms > 0

    @patch("canary.analysis.objectives._RETRY_WAIT", wait_none())
    @patch("canary.analysis.objectives.ChatAnthropic")
    async def test_prompt_contains_article_refs(self, mock_chat_cls):
        corrected = _mock_objective()
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            return_value={
                "parsed": RequoteResult(corrections=[corrected]),
                "raw": mock_raw_msg,
            }
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        await requote_citations([_mock_objective()], "source text here")

        call_args = mock_structured.ainvoke.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "Article 3(1)" in user_msg
        assert "shall disclose sustainability risks" in user_msg

    @patch("canary.analysis.objectives._RETRY_WAIT", wait_none())
    @patch("canary.analysis.objectives.ChatAnthropic")
    async def test_retry_on_api_error(self, mock_chat_cls):
        corrected = _mock_objective()
        mock_raw_msg = AsyncMock()
        mock_raw_msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}

        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            side_effect=[
                anthropic.APIStatusError(
                    message="overloaded",
                    response=MagicMock(status_code=529),
                    body=None,
                ),
                {
                    "parsed": RequoteResult(corrections=[corrected]),
                    "raw": mock_raw_msg,
                },
            ]
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        results, _ = await requote_citations([_mock_objective()], "source text")
        assert len(results) == 1
        assert mock_structured.ainvoke.call_count == 2

    @patch("canary.analysis.objectives._RETRY_WAIT", wait_none())
    @patch("canary.analysis.objectives.ChatAnthropic")
    async def test_exhausted_retries_raises(self, mock_chat_cls):
        mock_structured = AsyncMock()
        mock_structured.ainvoke = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=MagicMock())
        )

        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_chat_cls.return_value = mock_llm

        with pytest.raises(anthropic.APIConnectionError):
            await requote_citations([_mock_objective()], "source text")

        assert mock_structured.ainvoke.call_count == 2  # stop_after_attempt(2)
