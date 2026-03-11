"""Diff computation between document versions."""

import difflib


def compute_diff(old_text: str, new_text: str, context_lines: int = 5) -> list[str]:
    """Compute unified diff between old and new text."""
    return list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile="previous",
            tofile="current",
            n=context_lines,
            lineterm="",
        )
    )


def summarize_diff(diff_lines: list[str], max_lines: int = 200) -> str:
    """Truncate diff for LLM consumption."""
    truncated = diff_lines[:max_lines]
    summary = "\n".join(truncated)
    if len(diff_lines) > max_lines:
        summary += f"\n\n... ({len(diff_lines) - max_lines} more lines truncated)"
    return summary
