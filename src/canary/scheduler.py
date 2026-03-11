"""CANARY scheduler — entry point for running the pipeline."""

import argparse
import asyncio
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

logger = logging.getLogger(__name__)


async def run_canary(vault_enabled: bool = False) -> None:
    """Run the CANARY pipeline for all configured sources."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    logger.info("CANARY run %s starting (vault=%s)", run_id, vault_enabled)

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
            initial_state: CANARYState = {
                "current_source": source,
                "run_id": run_id,
                "vault_enabled": vault_enabled,
                "errors": [],
            }
            result = await graph.ainvoke(initial_state)

            errors = result.get("errors", [])
            if errors:
                for err in errors:
                    logger.error("  Error: %s", err)

            vault_path = result.get("vault_path")
            if vault_path:
                logger.info("  Report written to vault: %s", vault_path)
    finally:
        await fetcher.close()
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
