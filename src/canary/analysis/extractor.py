"""LLM-based regulatory change extraction using Claude with structured output."""

import logging
import time
from dataclasses import dataclass

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from canary.analysis.models import ExtractionResult

logger = logging.getLogger(__name__)

# Context budget for source text in change extraction.
# The diff is typically small; the source text is context for quote verification.
# Same model limits as objectives.py — 200K token context, reserve 30K for overhead.
_MAX_SOURCE_CHARS = (200_000 - 30_000) * 4  # ~680K chars

# Retry wait strategy — module-level for testability
_RETRY_WAIT = wait_exponential(multiplier=1, min=4, max=60)

SYSTEM_PROMPT = """\
You are a regulatory analysis expert specializing in ESG and sustainable finance regulation.

You are given a diff showing changes to a regulatory document, plus the full current source text.

Your task: extract every meaningful regulatory change into a structured format.

CRITICAL RULES:
1. Every claim MUST include a verbatim quote from the source document.
2. Copy exact words for supporting_quotes. Do NOT paraphrase.
3. If you cannot find a verbatim quote for a claim, do not make the claim.
4. Be conservative — only flag genuine regulatory changes, not formatting or numbering changes.
5. Assess materiality from the perspective of an EU asset manager operating Article 8/9 funds under SFDR.
"""

USER_PROMPT_TEMPLATE = """\
## Document Diff

{diff_text}

## Full Current Source Text

{source_text}

Extract all regulatory changes from this diff. For each change, provide verbatim quotes from \
the source text as evidence.
"""


@dataclass
class ExtractionMetrics:
    """Token usage and timing for a single extraction call."""

    model: str
    duration_ms: float
    input_tokens: int
    output_tokens: int


async def extract_changes(
    diff_text: str,
    source_text: str,
    model: str = "claude-sonnet-4-6",
) -> tuple[ExtractionResult, ExtractionMetrics]:
    """Extract structured regulatory changes from a document diff.

    Uses Claude with Pydantic structured output to ensure schema compliance.
    Returns (extraction_result, metrics).
    """
    llm = ChatAnthropic(model=model, temperature=0, max_tokens=4096)
    structured_llm = llm.with_structured_output(ExtractionResult, include_raw=True)

    if len(source_text) > _MAX_SOURCE_CHARS:
        logger.warning(
            "Source text truncated from %d to %d chars for extraction",
            len(source_text), _MAX_SOURCE_CHARS,
        )

    user_message = USER_PROMPT_TEMPLATE.format(
        diff_text=diff_text,
        source_text=source_text[:_MAX_SOURCE_CHARS],
    )

    logger.info("Extracting changes via %s", model)
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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]
        )

    raw_result = await _invoke()

    duration_ms = (time.monotonic() - start) * 1000

    # Extract token usage from raw response
    raw_msg: AIMessage = raw_result["raw"]
    usage = getattr(raw_msg, "usage_metadata", None) or {}
    input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
    output_tokens = usage.get("output_tokens", 0) if isinstance(usage, dict) else 0

    extraction: ExtractionResult = raw_result["parsed"]
    extraction_metrics = ExtractionMetrics(
        model=model,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )

    logger.info(
        "Extracted %d changes in %.0fms (tokens: %d in, %d out)",
        len(extraction.changes),
        duration_ms,
        input_tokens,
        output_tokens,
    )
    return extraction, extraction_metrics
