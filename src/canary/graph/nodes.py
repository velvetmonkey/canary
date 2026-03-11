"""LangGraph node functions for the CANARY pipeline."""

import json
import logging

from canary.analysis.extractor import extract_changes
from canary.analysis.mapper import tag_changes
from canary.analysis.verifier import verify_citations
from canary.detection.differ import compute_diff, summarize_diff
from canary.detection.hasher import compute_hash
from canary.detection.store import DocumentStore
from canary.fetchers.base import BaseFetcher
from canary.graph.state import CANARYState
from canary.output.schema import generate_change_report
from canary.output.vault import VaultWriter

logger = logging.getLogger(__name__)

# Module-level singletons (set by graph builder)
_fetcher: BaseFetcher | None = None
_store: DocumentStore | None = None
_vault_writer: VaultWriter | None = None


def set_fetcher(fetcher: BaseFetcher) -> None:
    global _fetcher
    _fetcher = fetcher


def set_store(store: DocumentStore) -> None:
    global _store
    _store = store


def set_vault_writer(writer: VaultWriter) -> None:
    global _vault_writer
    _vault_writer = writer


async def fetch_source(state: CANARYState) -> dict:
    """Fetch the current source document from EUR-Lex."""
    assert _fetcher is not None, "Fetcher not initialized"
    source = state["current_source"]
    celex_id = source["celex_id"]

    logger.info("Fetching %s (%s)", source["label"], celex_id)
    try:
        text, _ = await _fetcher.fetch_text(celex_id)
        if text is None:
            return {"fetched_text": None, "errors": ["ETag unchanged — skipping"]}
        return {"fetched_text": text}
    except Exception as e:
        logger.error("Fetch failed for %s: %s", celex_id, e)
        return {"fetched_text": None, "errors": [f"Fetch error: {e}"]}


async def detect_change(state: CANARYState) -> dict:
    """Compare fetched text against stored hash, compute diff if changed."""
    assert _store is not None, "Store not initialized"

    text = state.get("fetched_text")
    if text is None:
        return {"changed": False}

    source = state["current_source"]
    celex_id = source["celex_id"]
    new_hash = compute_hash(text)

    existing = _store.get_state(celex_id)
    is_first_run = existing is None

    if is_first_run:
        logger.info("First run for %s — storing baseline", celex_id)
        _store.upsert_state(celex_id, new_hash, text)
        _store.log_change(celex_id, None, new_hash, run_id=state.get("run_id"))
        return {
            "changed": False,
            "is_first_run": True,
            "new_hash": new_hash,
            "old_hash": None,
            "diff_text": None,
        }

    old_hash = existing["hash"]
    if old_hash == new_hash:
        logger.info("No change detected for %s", celex_id)
        _store.upsert_state(celex_id, new_hash, text)  # updates last_checked
        return {"changed": False, "is_first_run": False, "new_hash": new_hash, "old_hash": old_hash}

    # Changed!
    old_text = existing["text"]
    diff_lines = compute_diff(old_text, text)
    diff_summary = summarize_diff(diff_lines)

    _store.upsert_state(celex_id, new_hash, text)
    _store.log_change(celex_id, old_hash, new_hash, diff_summary=diff_summary, run_id=state.get("run_id"))

    logger.info("Change detected for %s — %d diff lines", celex_id, len(diff_lines))
    return {
        "changed": True,
        "is_first_run": False,
        "new_hash": new_hash,
        "old_hash": old_hash,
        "diff_text": diff_summary,
    }


async def extract_obligations(state: CANARYState) -> dict:
    """Extract structured regulatory changes from the diff using Claude."""
    diff_text = state.get("diff_text", "")
    source_text = state.get("fetched_text", "")
    celex_id = state["current_source"]["celex_id"]

    if not diff_text:
        return {"extraction": None}

    model = state.get("model", "claude-sonnet-4-6")
    try:
        extraction, extraction_metrics = await extract_changes(diff_text, source_text, model=model)
    except Exception as e:
        logger.error("Extraction failed for %s: %s", celex_id, e)
        return {
            "extraction": None,
            "extraction_metrics": None,
            "errors": state.get("errors", []) + [f"Extraction error: {e}"],
        }

    extraction.source_celex_id = celex_id

    # Quality check: non-trivial diff but zero changes extracted
    if diff_text.strip() and len(extraction.changes) == 0:
        logger.warning("Extraction returned 0 changes for non-empty diff on %s", celex_id)

    return {"extraction": extraction, "extraction_metrics": extraction_metrics}


async def verify_citations_node(state: CANARYState) -> dict:
    """Mechanically verify all citations in the extraction."""
    extraction = state.get("extraction")
    source_text = state.get("fetched_text", "")

    if extraction is None:
        return {"verification": None}

    report = verify_citations(extraction, source_text)
    if not report.all_verified:
        logger.warning(
            "%d unverified citations for %s",
            report.unverified_count,
            state["current_source"]["celex_id"],
        )
    return {"verification": report}


async def output_results(state: CANARYState) -> dict:
    """Generate and print the change report."""
    source = state["current_source"]
    extraction = state.get("extraction")
    verification = state.get("verification")

    if state.get("is_first_run"):
        result = {
            "status": "baseline_stored",
            "source": source["label"],
            "celex_id": source["celex_id"],
            "hash": state.get("new_hash"),
            "message": "First run — baseline indexed, no changes to report.",
        }
        logger.info("Baseline stored for %s: %s", source["celex_id"], json.dumps(result))
        return {"report": json.dumps(result)}

    if not state.get("changed"):
        result = {
            "status": "no_change",
            "source": source["label"],
            "celex_id": source["celex_id"],
            "message": "No changes detected.",
        }
        logger.info("No change for %s", source["celex_id"])
        return {"report": json.dumps(result)}

    # Generate markdown report
    tags = None
    if extraction:
        tags = tag_changes(extraction, regulation="SFDR", jurisdiction="EU")

    report_md = generate_change_report(
        source=source,
        extraction=extraction,
        verification=verification,
        tags=tags,
        run_id=state.get("run_id", "unknown"),
    )

    result = {
        "status": "changes_detected",
        "source": source["label"],
        "celex_id": source["celex_id"],
        "change_count": len(extraction.changes) if extraction else 0,
        "all_citations_verified": verification.all_verified if verification else None,
        "tags": tags,
    }
    logger.info("Changes detected for %s: %s", source["celex_id"], json.dumps(result))
    logger.debug("Markdown report:\n%s", report_md)

    return {"report": report_md, "tags": tags}


async def write_to_vault(state: CANARYState) -> dict:
    """Write the change report to the Obsidian vault via Flywheel MCP."""
    if not state.get("vault_enabled") or _vault_writer is None:
        return {}

    report = state.get("report")
    source = state["current_source"]
    run_id = state.get("run_id", "unknown")

    # Only write vault reports for actual changes (not baselines or no-change)
    if not state.get("changed") or not report:
        return {}

    vault_path = await _vault_writer.write_report(
        report_md=report,
        source_id=source["id"],
        run_id=run_id,
    )

    errors = []
    if vault_path is None and state.get("changed"):
        errors = state.get("errors", []) + ["Vault write failed for change report"]

    if vault_path:
        # Log to daily note
        extraction = state.get("extraction")
        change_count = len(extraction.changes) if extraction else 0
        severity = "unknown"
        if extraction:
            if any(c.materiality == "high" for c in extraction.changes):
                severity = "high"
            elif any(c.materiality == "medium" for c in extraction.changes):
                severity = "medium"
            else:
                severity = "low"

        await _vault_writer.log_to_daily(
            f"CANARY detected {change_count} {severity}-severity "
            f"{source['label']} change(s) — see [[{vault_path}]]"
        )

    result = {"vault_path": vault_path}
    if errors:
        result["errors"] = errors
    return result
