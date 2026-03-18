"""Re-import existing objective files into vault with wikilinks enabled."""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from canary.output.schema import _apply_wikilinks
from canary.output.vault import VaultWriter, _split_frontmatter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).parent.parent / "output" / "compliance" / "objectives"


async def main() -> None:
    load_dotenv()

    writer = VaultWriter()
    logger.info("Connecting to Flywheel MCP...")
    await writer.connect()

    # Collect all objective files
    files = sorted(OUTPUT_DIR.rglob("*.md"))
    files = [f for f in files if f.name != "README.md"]
    logger.info("Found %d objective files to import", len(files))

    written = 0
    errors = 0
    for i, filepath in enumerate(files, 1):
        # Derive vault path from relative path: sfdr-l1/article-3-1.md
        rel = filepath.relative_to(OUTPUT_DIR)
        vault_path = f"{writer._output_root}/objectives/{rel}"

        content = filepath.read_text()
        frontmatter, body = _split_frontmatter(content)

        # Apply CANARY wikilinks (article cross-refs + regulation entities)
        self_article = frontmatter.get("article")
        body = _apply_wikilinks(body, self_article)

        try:
            result = await writer._call_tool(
                "vault_create_note",
                {
                    "path": vault_path,
                    "content": body,
                    "frontmatter": frontmatter,
                    "overwrite": True,
                    "suggestOutgoingLinks": True,
                },
            )
            result_str = str(result) if result else ""
            if "Wikilinks:" in result_str or "Suggested:" in result_str:
                logger.info("[%d/%d] %s — %s", i, len(files), vault_path, result_str)
            else:
                logger.info("[%d/%d] %s", i, len(files), vault_path)
            written += 1
        except Exception as e:
            logger.error("[%d/%d] %s — FAILED: %s", i, len(files), vault_path, e)
            errors += 1

    await writer.disconnect()
    logger.info("=== Done: %d written, %d errors ===", written, errors)


if __name__ == "__main__":
    asyncio.run(main())
