"""Flywheel MCP vault writer — writes change reports to Obsidian vault.

Uses langchain-mcp-adapters to connect to the flywheel-memory MCP server
via stdio transport and invoke vault tools directly.
"""

import logging
import os
from datetime import date
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

# Default path to flywheel-memory MCP server
DEFAULT_MCP_SERVER = os.path.expanduser(
    "~/src/flywheel-memory/packages/mcp-server/dist/index.js"
)
DEFAULT_VAULT_PATH = os.path.expanduser("~/obsidian/Canary")


class VaultWriter:
    """Writes CANARY reports to Obsidian vault via Flywheel MCP."""

    def __init__(
        self,
        mcp_server_path: str | None = None,
        vault_path: str | None = None,
    ) -> None:
        self._server_path = mcp_server_path or os.environ.get(
            "CANARY_MCP_SERVER", DEFAULT_MCP_SERVER
        )
        self._vault_path = vault_path or os.environ.get("FLYWHEEL_VAULT", DEFAULT_VAULT_PATH)
        self._client: MultiServerMCPClient | None = None
        self._tools: dict[str, BaseTool] = {}

    async def connect(self) -> None:
        """Connect to flywheel-memory MCP server and load tools."""
        # Inherit parent env so node/PATH work, then overlay our settings
        env = {
            **os.environ,
            "VAULT_PATH": self._vault_path,
            "PROJECT_PATH": self._vault_path,
            "FLYWHEEL_PRESET": "writer",
        }
        self._client = MultiServerMCPClient(
            {
                "flywheel": {
                    "command": "node",
                    "args": [self._server_path],
                    "transport": "stdio",
                    "env": env,
                    "cwd": self._vault_path,
                }
            }
        )
        tools = await self._client.get_tools()
        self._tools = {t.name: t for t in tools}
        logger.info("Connected to flywheel MCP — %d tools available", len(self._tools))

    async def disconnect(self) -> None:
        """Clean up client reference. Sessions are per-tool-call, no persistent connection."""
        self._client = None
        self._tools = {}

    async def _call_tool(self, name: str, args: dict[str, Any]) -> Any:
        """Call a flywheel MCP tool by name."""
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools.keys()))
            raise RuntimeError(f"Tool '{name}' not found. Available: {available}")
        return await tool.ainvoke(args)

    async def check_duplicate(self, run_id: str) -> bool:
        """Check if a report with this run_id already exists in the vault."""
        try:
            result = await self._call_tool(
                "search",
                {"query": f"canary_run_id: {run_id}", "scope": "content", "limit": 1},
            )
            if isinstance(result, dict) and result.get("results"):
                return True
            if isinstance(result, list) and len(result) > 0:
                return True
        except Exception as e:
            logger.warning("Duplicate check failed: %s", e)
        return False

    async def write_report(
        self,
        report_md: str,
        source_id: str,
        run_id: str,
    ) -> str | None:
        """Write a change report note to the vault.

        Returns the path of the created note, or None if duplicate/error.
        """
        # Check for duplicates
        if await self.check_duplicate(run_id):
            logger.info("Duplicate report for run %s — skipping", run_id)
            return None

        today = date.today().isoformat()
        note_path = f"work/compliance/reports/{today}-{source_id}.md"

        try:
            await self._call_tool(
                "vault_create_note",
                {"path": note_path, "content": report_md},
            )
            logger.info("Wrote report to %s", note_path)
            return note_path
        except Exception as e:
            logger.error("Failed to write report: %s", e)
            return None

    async def write_objective(
        self,
        note_md: str,
        article_ref: str,
        regulation_short: str,
    ) -> str | None:
        """Write a compliance objective note to the vault.

        Returns the path of the created note, or None on error.
        """
        # Sanitize article ref for filename: "Article 4(1)(a)" → "article-4-1-a"
        safe_name = article_ref.lower().replace(" ", "-").replace("(", "-").replace(")", "")
        safe_name = safe_name.replace("--", "-").rstrip("-")
        note_path = f"work/compliance/objectives/{regulation_short}/{safe_name}.md"

        try:
            await self._call_tool(
                "vault_create_note",
                {"path": note_path, "content": note_md},
            )
            logger.info("Wrote objective to %s", note_path)
            return note_path
        except Exception as e:
            logger.error("Failed to write objective: %s", e)
            return None

    async def log_to_daily(self, message: str) -> None:
        """Append a log entry to today's daily note."""
        today = date.today().isoformat()
        daily_path = f"daily-notes/{today}.md"

        try:
            await self._call_tool(
                "vault_add_to_section",
                {
                    "path": daily_path,
                    "section": "Log",
                    "content": message,
                    "format": "timestamp-bullet",
                },
            )
            logger.info("Logged to daily note: %s", daily_path)
        except Exception as e:
            logger.warning("Failed to log to daily note: %s", e)
