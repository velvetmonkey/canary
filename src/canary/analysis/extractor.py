"""LLM-based regulatory change extraction using Claude with structured output."""

import logging

from langchain_anthropic import ChatAnthropic

from canary.analysis.models import ExtractionResult

logger = logging.getLogger(__name__)

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


async def extract_changes(
    diff_text: str,
    source_text: str,
    model: str = "claude-sonnet-4-6",
) -> ExtractionResult:
    """Extract structured regulatory changes from a document diff.

    Uses Claude with Pydantic structured output to ensure schema compliance.
    """
    llm = ChatAnthropic(model=model, temperature=0, max_tokens=4096)
    structured_llm = llm.with_structured_output(ExtractionResult)

    user_message = USER_PROMPT_TEMPLATE.format(
        diff_text=diff_text,
        source_text=source_text[:50_000],  # truncate very long docs
    )

    logger.info("Extracting changes via %s", model)
    result = await structured_llm.ainvoke(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
    )
    logger.info("Extracted %d changes", len(result.changes))
    return result
