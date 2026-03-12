"""LLM-based compliance objective extraction using Claude with structured output.

Handles arbitrarily large documents by splitting into overlapping chunks
and merging results with article-level deduplication.
"""

import logging
import time
from dataclasses import dataclass

import anthropic
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from canary.analysis.models import ComplianceObjective, ObjectiveExtraction

logger = logging.getLogger(__name__)

# --- Context budget ---
# Sonnet/Opus/Haiku all support 200K tokens.
# Reserve headroom for system prompt (~500 tokens), user template (~100 tokens),
# and max_tokens output (8192). Conservative 4 chars/token for regulatory text.
_MODEL_CONTEXT_TOKENS = 200_000
_RESERVED_TOKENS = 30_000  # system + template + output + safety margin
_CHARS_PER_TOKEN = 4
_MAX_SOURCE_CHARS = (_MODEL_CONTEXT_TOKENS - _RESERVED_TOKENS) * _CHARS_PER_TOKEN  # ~680K
_CHUNK_OVERLAP_CHARS = 8_000  # enough to capture an article that straddles a boundary

# Retry wait strategy — module-level for testability
_RETRY_WAIT = wait_exponential(multiplier=1, min=4, max=60)

SYSTEM_PROMPT = """\
You are a regulatory compliance expert specializing in EU sustainable finance regulation (SFDR, Taxonomy, CSRD).

You are given the full text of a regulation (or a section of one). Your task: extract the {count} most \
important compliance objectives — the concrete obligations that firms must fulfil.

CRITICAL RULES:
1. Focus on substantive obligations, not procedural/administrative articles (entry into force, competent authorities, etc).
2. Each objective must map to a specific Article or sub-article.
3. The verbatim_quote MUST be copied exactly from the source text — do NOT paraphrase.
   Quote a SINGLE contiguous sentence or clause (max 300 chars). Do NOT stitch together text from multiple sub-paragraphs.
4. Assess materiality from the perspective of an EU asset manager operating Article 8/9 funds.
5. Order by importance: most material obligations first.
6. obligation_type must be one of: disclosure, reporting, governance, process, prohibition.
7. Keep "what" plain-language and actionable — a compliance officer should understand what to do.
"""

USER_PROMPT_TEMPLATE = """\
## Regulation Text

{source_text}

Extract the {count} most important compliance objectives from this regulation text. \
For each, provide the exact article reference, a plain-language description of \
the obligation, and a verbatim quote establishing it.
"""


@dataclass
class ObjectiveMetrics:
    """Token usage and timing for objective extraction."""

    model: str
    duration_ms: float
    input_tokens: int
    output_tokens: int
    objectives_extracted: int
    chunks: int = 1


@dataclass
class _ChunkResult:
    extraction: ObjectiveExtraction
    metrics: ObjectiveMetrics


async def _extract_single(
    source_text: str,
    count: int,
    model: str,
) -> tuple[ObjectiveExtraction, ObjectiveMetrics]:
    """Single-pass extraction (no chunking). Source text must fit in context."""
    # ~400 tokens per objective + overhead for wrapper fields
    max_tokens = min(max(count * 400 + 2000, 8192), 32768)
    llm = ChatAnthropic(model=model, temperature=0, max_tokens=max_tokens)
    structured_llm = llm.with_structured_output(ObjectiveExtraction, include_raw=True)

    user_message = USER_PROMPT_TEMPLATE.format(
        source_text=source_text,
        count=count,
    )
    system_message = SYSTEM_PROMPT.format(count=count)

    logger.info("Extracting %d objectives via %s (%d chars)", count, model, len(source_text))
    start = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=_RETRY_WAIT,
        retry=retry_if_exception_type(
            (anthropic.APIStatusError, anthropic.APIConnectionError)
        ),
        reraise=True,
    )
    async def _invoke():
        return await structured_llm.ainvoke(
            [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ]
        )

    raw_result = await _invoke()

    duration_ms = (time.monotonic() - start) * 1000

    raw_msg = raw_result["raw"]
    usage = getattr(raw_msg, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
    output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0

    extraction: ObjectiveExtraction = raw_result["parsed"]
    metrics = ObjectiveMetrics(
        model=model,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        objectives_extracted=len(extraction.objectives),
    )

    logger.info(
        "Extracted %d objectives in %.0fms (tokens: %d in, %d out)",
        len(extraction.objectives),
        duration_ms,
        input_tokens,
        output_tokens,
    )
    return extraction, metrics


def _split_chunks(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks, breaking at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars

        if end < len(text):
            # Try to break at a double-newline (paragraph boundary) near the end
            zone_start = max(start + 1, end - 2000)
            break_zone = text[zone_start:end]
            para_break = break_zone.rfind("\n\n")
            if para_break != -1:
                end = zone_start + para_break
            else:
                # Fall back to single newline
                line_break = break_zone.rfind("\n")
                if line_break != -1:
                    end = zone_start + line_break

        # Ensure forward progress
        end = max(end, start + 1)

        chunks.append(text[start:end])

        # If we've reached the end, stop
        if end >= len(text):
            break

        # Next chunk starts overlap chars before the end of this one
        start = max(end - overlap, start + 1)

    logger.info(
        "Split %d chars into %d chunks (max %d, overlap %d)",
        len(text), len(chunks), max_chars, overlap,
    )
    return chunks


async def extract_objectives(
    source_text: str,
    count: int = 10,
    model: str = "claude-sonnet-4-6",
) -> tuple[ObjectiveExtraction, ObjectiveMetrics]:
    """Extract structured compliance objectives from regulation text.

    Handles documents of any size:
    - Documents under ~680K chars: single extraction pass
    - Larger documents: split into overlapping chunks, extract from each,
      deduplicate by article reference, merge

    Returns (extraction_result, aggregate_metrics).
    """
    if len(source_text) <= _MAX_SOURCE_CHARS:
        return await _extract_single(source_text, count=count, model=model)

    # --- Chunked extraction ---
    chunks = _split_chunks(source_text, _MAX_SOURCE_CHARS, _CHUNK_OVERLAP_CHARS)
    logger.info(
        "Document too large for single pass (%d chars > %d limit), "
        "extracting from %d chunks",
        len(source_text), _MAX_SOURCE_CHARS, len(chunks),
    )

    all_objectives = []
    seen_articles: set[str] = set()
    total_input = 0
    total_output = 0
    total_duration = 0.0
    regulation_name = ""
    source_celex_id = ""

    for i, chunk in enumerate(chunks):
        logger.info(
            "Chunk %d/%d: %d chars (articles may overlap with adjacent chunks)",
            i + 1, len(chunks), len(chunk),
        )
        extraction, metrics = await _extract_single(chunk, count=count, model=model)

        total_input += metrics.input_tokens
        total_output += metrics.output_tokens
        total_duration += metrics.duration_ms

        # Keep metadata from first chunk
        if not regulation_name:
            regulation_name = extraction.regulation_name
            source_celex_id = extraction.source_celex_id

        # Deduplicate by article reference
        for obj in extraction.objectives:
            if obj.article not in seen_articles:
                all_objectives.append(obj)
                seen_articles.add(obj.article)
            else:
                logger.debug("Skipping duplicate article from chunk %d: %s", i + 1, obj.article)

    merged = ObjectiveExtraction(
        objectives=all_objectives,
        source_celex_id=source_celex_id,
        regulation_name=regulation_name,
        summary=(
            f"Complete extraction from {len(chunks)} chunks: "
            f"{len(all_objectives)} unique objectives across {len(seen_articles)} articles"
        ),
    )

    aggregate_metrics = ObjectiveMetrics(
        model=model,
        duration_ms=total_duration,
        input_tokens=total_input,
        output_tokens=total_output,
        objectives_extracted=len(all_objectives),
        chunks=len(chunks),
    )

    logger.info(
        "Merged extraction: %d unique objectives from %d chunks "
        "(total: %d in, %d out tokens, %.1fs)",
        len(all_objectives), len(chunks),
        total_input, total_output, total_duration / 1000,
    )

    return merged, aggregate_metrics


# --- Citation retry ---

REQUOTE_SYSTEM = """\
You are a regulatory compliance expert. You previously extracted compliance objectives \
from a regulation, but some verbatim quotes could not be verified against the source text.

Your task: for each objective listed below, find the EXACT passage in the source text \
that establishes the obligation and return it as a corrected verbatim_quote.

RULES:
1. The quote MUST be copied character-for-character from the source text.
2. Do NOT paraphrase, summarize, or combine passages.
3. Keep quotes under 300 characters — pick the single most relevant sentence or clause.
4. If you genuinely cannot find a matching passage, return the original quote unchanged.
"""

REQUOTE_USER_TEMPLATE = """\
## Source Text

{source_text}

## Objectives needing corrected quotes

{objectives_list}

For each objective above, return a corrected verbatim_quote copied exactly from the source text.
"""


class RequoteResult(BaseModel):
    """Result of re-quoting unverified citations."""

    corrections: list[ComplianceObjective]


async def requote_citations(
    objectives: list[ComplianceObjective],
    source_text: str,
    model: str = "claude-sonnet-4-6",
) -> tuple[list[ComplianceObjective], ObjectiveMetrics]:
    """Re-extract verbatim quotes for objectives that failed citation verification.

    Sends the source text + the failed objectives back to Claude and asks for
    exact quotes. Returns corrected objectives and metrics.
    """
    obj_lines = []
    for i, obj in enumerate(objectives, 1):
        obj_lines.append(
            f"{i}. {obj.article} — {obj.title}\n"
            f"   obligation_type: {obj.obligation_type}\n"
            f"   who: {obj.who}\n"
            f"   what: {obj.what}\n"
            f"   original quote: {obj.verbatim_quote[:200]}"
        )

    max_tokens = min(max(len(objectives) * 400 + 2000, 4096), 16384)
    llm = ChatAnthropic(model=model, temperature=0, max_tokens=max_tokens)
    structured_llm = llm.with_structured_output(RequoteResult, include_raw=True)

    user_msg = REQUOTE_USER_TEMPLATE.format(
        source_text=source_text,
        objectives_list="\n".join(obj_lines),
    )

    logger.info("Re-quoting %d unverified citations via %s", len(objectives), model)
    start = time.monotonic()

    @retry(
        stop=stop_after_attempt(2),
        wait=_RETRY_WAIT,
        retry=retry_if_exception_type(
            (anthropic.APIStatusError, anthropic.APIConnectionError)
        ),
        reraise=True,
    )
    async def _invoke():
        return await structured_llm.ainvoke(
            [
                {"role": "system", "content": REQUOTE_SYSTEM},
                {"role": "user", "content": user_msg},
            ]
        )

    raw_result = await _invoke()
    duration_ms = (time.monotonic() - start) * 1000

    raw_msg = raw_result["raw"]
    usage = getattr(raw_msg, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
    output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0

    result: RequoteResult = raw_result["parsed"]

    metrics = ObjectiveMetrics(
        model=model,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        objectives_extracted=len(result.corrections),
    )

    logger.info(
        "Re-quoted %d objectives in %.0fms (tokens: %d in, %d out)",
        len(result.corrections), duration_ms, input_tokens, output_tokens,
    )

    return result.corrections, metrics
