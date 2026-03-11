"""LangGraph node functions for the CANARY pipeline."""

import json
import logging
from pathlib import Path

import yaml

from canary.analysis.extractor import extract_changes
from canary.analysis.mapper import tag_changes
from canary.analysis.verifier import verify_citations
from canary.detection.differ import compute_diff, summarize_diff
from canary.detection.hasher import compute_hash
from canary.detection.store import DocumentStore
from canary.fetchers.eurlex import EurLexFetcher
from canary.graph.state import CANARYState
from canary.output.schema import generate_change_report

logger = logging.getLogger(__name__)

# Module-level singletons (set by graph builder)
_fetcher: EurLexFetcher | None = None
_store: DocumentStore | None = None


def set_fetcher(fetcher: EurLexFetcher) -> None:
    global _fetcher
    _fetcher = fetcher


def set_store(store: DocumentStore) -> None:
    global _store
    _store = store


async def load_sources(state: CANARYState) -> dict:
    """Load source configurations from sources.yaml."""
    config_path = Path("config/sources.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return {"sources": config["sources"]}


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

    extraction = await extract_changes(diff_text, source_text)
    extraction.source_celex_id = celex_id
    return {"extraction": extraction}


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
        print(json.dumps(result, indent=2))
        return {"report": json.dumps(result)}

    if not state.get("changed"):
        result = {
            "status": "no_change",
            "source": source["label"],
            "celex_id": source["celex_id"],
            "message": "No changes detected.",
        }
        print(json.dumps(result, indent=2))
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

    # Print both structured JSON and markdown
    result = {
        "status": "changes_detected",
        "source": source["label"],
        "celex_id": source["celex_id"],
        "change_count": len(extraction.changes) if extraction else 0,
        "all_citations_verified": verification.all_verified if verification else None,
        "tags": tags,
    }
    print(json.dumps(result, indent=2))
    print("\n--- Markdown Report ---\n")
    print(report_md)

    return {"report": report_md, "tags": tags}
