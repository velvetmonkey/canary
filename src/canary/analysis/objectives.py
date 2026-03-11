"""LLM-based compliance objective extraction using Claude with structured output."""

import logging
import time
from dataclasses import dataclass

from langchain_anthropic import ChatAnthropic

from canary.analysis.models import ObjectiveExtraction

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a regulatory compliance expert specializing in EU sustainable finance regulation (SFDR, Taxonomy, CSRD).

You are given the full text of a regulation. Your task: extract the {count} most important compliance \
objectives — the concrete obligations that firms must fulfil.

CRITICAL RULES:
1. Focus on substantive obligations, not procedural/administrative articles (entry into force, competent authorities, etc).
2. Each objective must map to a specific Article or sub-article.
3. The verbatim_quote MUST be copied exactly from the source text — do NOT paraphrase.
4. Assess materiality from the perspective of an EU asset manager operating Article 8/9 funds.
5. Order by importance: most material obligations first.
6. obligation_type must be one of: disclosure, reporting, governance, process, prohibition.
7. Keep "what" plain-language and actionable — a compliance officer should understand what to do.
"""

USER_PROMPT_TEMPLATE = """\
## Regulation Text

{source_text}

Extract the {count} most important compliance objectives from this regulation. \
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


async def extract_objectives(
    source_text: str,
    count: int = 10,
    model: str = "claude-sonnet-4-6",
) -> tuple[ObjectiveExtraction, ObjectiveMetrics]:
    """Extract structured compliance objectives from regulation text.

    Returns (extraction_result, metrics).
    """
    llm = ChatAnthropic(model=model, temperature=0, max_tokens=8192)
    structured_llm = llm.with_structured_output(ObjectiveExtraction, include_raw=True)

    user_message = USER_PROMPT_TEMPLATE.format(
        source_text=source_text[:80_000],  # larger window for full doc
        count=count,
    )

    system_message = SYSTEM_PROMPT.format(count=count)

    logger.info("Extracting %d objectives via %s", count, model)
    start = time.monotonic()

    raw_result = await structured_llm.ainvoke(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
    )

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
