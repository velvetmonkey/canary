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


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="CANARY — ESG regulatory change monitor")
    parser.add_argument(
        "--no-vault",
        action="store_true",
        help="Disable vault writes (console output only)",
    )
    args = parser.parse_args()
    asyncio.run(run_canary(vault_enabled=not args.no_vault))


if __name__ == "__main__":
    main()
