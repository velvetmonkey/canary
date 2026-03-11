"""CANARY scheduler — entry point for running the pipeline."""

import argparse
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

import yaml
from dotenv import load_dotenv

from canary.detection.store import DocumentStore
from canary.fetchers.eurlex import EurLexFetcher
from canary.graph.graph import build_graph
from canary.graph.nodes import set_fetcher, set_store, set_vault_writer
from canary.graph.state import CANARYState
from canary.output.schema import generate_objective_note
from canary.output.vault import VaultWriter
from canary.tracing import RunMetrics, configure_langsmith

logger = logging.getLogger(__name__)


async def run_canary(vault_enabled: bool = False) -> None:
    """Run the CANARY pipeline for all configured sources."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_id = f"run-{uuid.uuid4().hex[:12]}"

    # Configure LangSmith tracing
    tracing_enabled = configure_langsmith(run_id)

    # Initialize run metrics
    metrics = RunMetrics(run_id=run_id)
    metrics.start()

    logger.info(
        "CANARY run %s starting (vault=%s, tracing=%s)", run_id, vault_enabled, tracing_enabled
    )

    # Initialize components
    db_path = Path(os.environ.get("CANARY_DB_PATH", "data/canary.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = DocumentStore(db_path)
    fetcher = EurLexFetcher()
    vault_writer: VaultWriter | None = None

    set_store(store)
    set_fetcher(fetcher)

    if vault_enabled:
        vault_writer = VaultWriter()
        await vault_writer.connect()
        set_vault_writer(vault_writer)
        logger.info("Vault writer connected")

    graph = build_graph()

    with open("config/sources.yaml") as f:
        config = yaml.safe_load(f)

    sources = config["sources"]
    logger.info("Processing %d sources", len(sources))

    try:
        for source in sources:
            logger.info("--- Processing: %s ---", source["label"])

            # Track per-source metrics
            source_metrics = metrics.start_source(source["celex_id"], source["label"])

            initial_state: CANARYState = {
                "current_source": source,
                "run_id": run_id,
                "vault_enabled": vault_enabled,
                "errors": [],
            }

            try:
                result = await graph.ainvoke(initial_state)

                # Update source metrics from result
                if result.get("is_first_run"):
                    source_metrics.status = "baseline"
                elif result.get("changed"):
                    source_metrics.status = "changed"
                    extraction = result.get("extraction")
                    if extraction:
                        source_metrics.change_count = len(extraction.changes)
                    verification = result.get("verification")
                    if verification:
                        source_metrics.citations_total = len(verification.results)
                        source_metrics.citations_verified = (
                            source_metrics.citations_total - verification.unverified_count
                        )
                    # Track token usage
                    ext_metrics = result.get("extraction_metrics")
                    if ext_metrics:
                        metrics.extraction_tokens_in += ext_metrics.input_tokens
                        metrics.extraction_tokens_out += ext_metrics.output_tokens
                else:
                    source_metrics.status = "no_change"

                source_metrics.hash = result.get("new_hash")
                source_metrics.vault_path = result.get("vault_path")

                errors = result.get("errors", [])
                if errors:
                    source_metrics.error = "; ".join(errors)
                    for err in errors:
                        logger.error("  Error: %s", err)

            except Exception as e:
                source_metrics.status = "error"
                source_metrics.error = str(e)
                logger.error("Pipeline error for %s: %s", source["label"], e)

            metrics.finish_source(source_metrics)

    finally:
        await fetcher.close()

        # Finalize and persist run metrics
        metrics.finish()
        store.save_run(metrics)

        # Print run summary
        summary = metrics.summary()
        logger.info("--- Run Summary ---")
        print(json.dumps(summary, indent=2))

        store.close()
        if vault_writer:
            await vault_writer.disconnect()

    logger.info("CANARY run %s complete", run_id)


async def run_extract_objectives(
    source_id: str | None = None,
    count: int = 10,
    vault_enabled: bool = True,
) -> None:
    """Extract compliance objectives from a regulation and write to vault."""
    from canary.analysis.objectives import extract_objectives

    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_id = f"obj-{uuid.uuid4().hex[:12]}"
    configure_langsmith(run_id)

    # Load sources
    with open("config/sources.yaml") as f:
        config = yaml.safe_load(f)

    sources = config["sources"]
    if source_id:
        sources = [s for s in sources if s["id"] == source_id]
        if not sources:
            logger.error("Source '%s' not found in sources.yaml", source_id)
            return

    # Just process the first source for objective extraction
    source = sources[0]
    celex_id = source["celex_id"]

    logger.info("Extracting %d objectives from %s (%s)", count, source["label"], celex_id)

    # Fetch the document
    fetcher = EurLexFetcher()
    try:
        text, _ = await fetcher.fetch_text(celex_id)
    finally:
        await fetcher.close()

    if not text:
        logger.error("Failed to fetch document")
        return

    logger.info("Fetched %d chars", len(text))

    # Extract objectives via Claude
    extraction, metrics = await extract_objectives(text, count=count)

    logger.info(
        "Extracted %d objectives — %s, %.1fs, %d/%d tokens",
        len(extraction.objectives),
        metrics.model,
        metrics.duration_ms / 1000,
        metrics.input_tokens,
        metrics.output_tokens,
    )

    # Connect vault writer
    vault_writer: VaultWriter | None = None
    if vault_enabled:
        vault_writer = VaultWriter()
        await vault_writer.connect()

    # Generate and write each objective note
    for i, obj in enumerate(extraction.objectives, 1):
        note_md = generate_objective_note(
            objective=obj,
            regulation_name=extraction.regulation_name,
            celex_id=celex_id,
            run_id=run_id,
            source_text=text,
        )

        print(f"\n{'='*60}")
        print(f"Objective {i}/{len(extraction.objectives)}: {obj.article} — {obj.title}")
        print(f"  Type: {obj.obligation_type} | Materiality: {obj.materiality}")
        print(f"  Who: {obj.who}")
        print(f"  What: {obj.what}")

        if vault_writer:
            # Derive short regulation name from source id
            reg_short = source["id"].lower()
            path = await vault_writer.write_objective(note_md, obj.article, reg_short)
            if path:
                print(f"  Vault: {path}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Run: {run_id}")
    print(f"Source: {source['label']} ({celex_id})")
    print(f"Objectives: {len(extraction.objectives)}")
    print(f"Tokens: {metrics.input_tokens} in / {metrics.output_tokens} out")
    print(f"Duration: {metrics.duration_ms / 1000:.1f}s")

    if vault_writer:
        # Log summary to daily note
        await vault_writer.log_to_daily(
            f"CANARY extracted {len(extraction.objectives)} compliance objectives "
            f"from {source['label']}"
        )
        await vault_writer.disconnect()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="CANARY — ESG regulatory change monitor")
    subparsers = parser.add_subparsers(dest="command")

    # Default: run change detection (no subcommand needed)
    parser.add_argument(
        "--no-vault",
        action="store_true",
        help="Disable vault writes (console output only)",
    )

    # extract-objectives subcommand
    obj_parser = subparsers.add_parser(
        "extract-objectives",
        help="Extract compliance objectives from a regulation",
    )
    obj_parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Source ID from sources.yaml (default: first source)",
    )
    obj_parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of objectives to extract (default: 10)",
    )
    obj_parser.add_argument(
        "--no-vault",
        action="store_true",
        help="Disable vault writes",
    )

    args = parser.parse_args()

    if args.command == "extract-objectives":
        asyncio.run(
            run_extract_objectives(
                source_id=args.source,
                count=args.count,
                vault_enabled=not args.no_vault,
            )
        )
    else:
        asyncio.run(run_canary(vault_enabled=not args.no_vault))


if __name__ == "__main__":
    main()
