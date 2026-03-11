"""CANARY scheduler — entry point for running the pipeline."""

import asyncio
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

from canary.detection.store import DocumentStore
from canary.fetchers.eurlex import EurLexFetcher
from canary.graph.graph import build_graph
from canary.graph.nodes import set_fetcher, set_store
from canary.graph.state import CANARYState

logger = logging.getLogger(__name__)


async def run_canary() -> None:
    """Run the CANARY pipeline for all configured sources."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    run_id = f"run-{uuid.uuid4().hex[:12]}"
    logger.info("CANARY run %s starting", run_id)

    # Initialize components
    db_path = Path(os.environ.get("CANARY_DB_PATH", "data/canary.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    store = DocumentStore(db_path)
    fetcher = EurLexFetcher()

    set_store(store)
    set_fetcher(fetcher)

    graph = build_graph()

    # Load sources
    import yaml

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
                "errors": [],
            }
            result = await graph.ainvoke(initial_state)

            errors = result.get("errors", [])
            if errors:
                for err in errors:
                    logger.error("  Error: %s", err)
    finally:
        await fetcher.close()
        store.close()

    logger.info("CANARY run %s complete", run_id)


def main() -> None:
    """CLI entry point."""
    asyncio.run(run_canary())


if __name__ == "__main__":
    main()
