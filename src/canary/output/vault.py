"""Flywheel MCP vault writer — writes change reports to Obsidian vault.

Uses langchain-mcp-adapters to connect to the flywheel-memory MCP server
via stdio transport and invoke vault tools directly.
"""

import json
import logging
import os
import re
import shlex
from datetime import date
from typing import Any

import yaml
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)


def _split_frontmatter(markdown: str) -> tuple[dict, str]:
    """Split YAML frontmatter from markdown body.

    Returns (frontmatter_dict, body_string). If no valid frontmatter
    is found, returns ({}, original_markdown).
    """
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown
    fm_str = markdown[4:end]
    body = markdown[end + 5:].lstrip("\n")
    try:
        fm = yaml.safe_load(fm_str) or {}
    except Exception:
        return {}, markdown
    return fm, body


def _search_results(result: Any) -> list[dict]:
    """Normalize Flywheel search responses across MCP adapter shapes."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (ValueError, TypeError):
            return []

    if isinstance(result, dict):
        notes = result.get("notes", result.get("results", []))
        return notes if isinstance(notes, list) else []

    if isinstance(result, list):
        # langchain-mcp-adapters can wrap tool output as text content blocks.
        if all(isinstance(item, dict) and "text" in item for item in result):
            normalized: list[dict] = []
            for item in result:
                normalized.extend(_search_results(item["text"]))
            return normalized
        return result

    return []

# Default path to flywheel-memory MCP server
DEFAULT_MCP_SERVER = os.path.expanduser(
    "/home/ben/flywheel/releases/current/packages/mcp-server/dist/index.js"
)
DEFAULT_VAULT_PATH = os.path.expanduser("~/obsidian/Canary")
DEFAULT_OUTPUT_ROOT = "work/compliance"
DEFAULT_DAILY_ROOT = "daily-notes"


def _server_command(server_path: str) -> tuple[str, list[str]]:
    """Build the stdio MCP command.

    CANARY_MCP_SERVER normally points at the Flywheel server JS file. For demos it
    may point at a full command line, such as seal wrapping node and the server.
    """
    if any(char.isspace() for char in server_path):
        parts = shlex.split(server_path)
        if not parts:
            raise RuntimeError("CANARY_MCP_SERVER command is empty")
        return parts[0], parts[1:]
    return "node", [server_path]


class VaultWriter:
    """Writes CANARY reports to Obsidian vault via Flywheel MCP."""

    def __init__(
        self,
        mcp_server_path: str | None = None,
        vault_path: str | None = None,
    ) -> None:
        self._server_path = os.path.expanduser(
            mcp_server_path or os.environ.get("CANARY_MCP_SERVER", DEFAULT_MCP_SERVER)
        )
        self._vault_path = os.path.expanduser(
            vault_path or os.environ.get("FLYWHEEL_VAULT", DEFAULT_VAULT_PATH)
        )
        self._output_root = os.environ.get("CANARY_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT)
        self._daily_root = os.environ.get("CANARY_DAILY_ROOT", DEFAULT_DAILY_ROOT)
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
        command, args = _server_command(self._server_path)
        self._client = MultiServerMCPClient(
            {
                "flywheel": {
                    "command": command,
                    "args": args,
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

    async def _create_note(self, args: dict[str, Any]) -> Any:
        """Create a note with the current Flywheel MCP note tool."""
        return await self._call_tool("note", {"action": "create", **args})

    async def search_by_type(self, type_name: str, limit: int = 50) -> list[dict]:
        """Search vault for notes matching a given type."""
        result = await self._call_tool(
            "search",
            {"query": type_name, "where": {"type": type_name}, "limit": limit},
        )
        return _search_results(result)

    async def check_duplicate(self, run_id: str) -> bool:
        """Check if a report with this run_id already exists in the vault."""
        try:
            result = await self._call_tool(
                "search",
                {"query": f"canary_run_id: {run_id}", "scope": "content", "limit": 1},
            )
            return bool(_search_results(result))
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
            logger.info("Duplicate report for run %s — skipping vault write", run_id)
            return None

        today = date.today().isoformat()
        note_path = f"{self._output_root}/reports/{today}-{source_id}.md"

        # Split frontmatter from body so the MCP tool processes them correctly
        # (avoids double frontmatter and ensures wikilinks only apply to body)
        frontmatter, body = _split_frontmatter(report_md)

        try:
            result = await self._create_note({
                "path": note_path,
                "content": body,
                "frontmatter": frontmatter,
                "overwrite": True,
            })
            self._log_vault_result("report", note_path, result)
            return note_path
        except Exception as e:
            logger.error("Failed to write report to vault: %s", e)
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
        safe_name = article_ref.lower()
        safe_name = re.sub(r"[^a-z0-9]+", "-", safe_name)
        safe_name = safe_name.strip("-")
        note_path = f"{self._output_root}/objectives/{regulation_short}/{safe_name}.md"

        # Split frontmatter from body so the MCP tool processes them correctly
        frontmatter, body = _split_frontmatter(note_md)

        try:
            result = await self._create_note({
                "path": note_path,
                "content": body,
                "frontmatter": frontmatter,
                "overwrite": True,
                "suggestOutgoingLinks": True,
            })
            self._log_vault_result("objective", note_path, result)
            return note_path
        except Exception as e:
            logger.error("Failed to write objective to vault: %s", e)
            return None

    async def write_readme(
        self,
        readme_md: str,
        path: str,
    ) -> str | None:
        """Write a README index note to the vault.

        Returns the path of the created note, or None on error.
        """
        frontmatter, body = _split_frontmatter(readme_md)
        try:
            result = await self._create_note({
                "path": path,
                "content": body,
                "frontmatter": frontmatter,
                "overwrite": True,
                "suggestOutgoingLinks": True,
            })
            self._log_vault_result("readme", path, result)
            return path
        except Exception as e:
            logger.error("Failed to write readme to vault: %s", e)
            return None

    def _log_vault_result(self, note_type: str, note_path: str, result: Any) -> None:
        """Log vault write result, extracting wikilink info if present."""
        result_str = str(result) if result else ""
        # Extract wikilink/suggestion info from MCP response
        if "Wikilinks:" in result_str or "Suggested:" in result_str:
            logger.info("Vault write [%s] %s — %s", note_type, note_path, result_str)
        else:
            logger.info("Vault write [%s] %s", note_type, note_path)
            if result_str:
                logger.debug("Vault response: %s", result_str)

    async def log_to_daily(self, message: str) -> None:
        """Append a log entry to today's daily note."""
        today = date.today().isoformat()
        daily_path = f"{self._daily_root}/{today}.md"

        try:
            await self._call_tool(
                "edit_section",
                {
                    "action": "add",
                    "path": daily_path,
                    "section": "Log",
                    "content": message,
                    "create_if_missing": True,
                    "format": "timestamp-bullet",
                    "skipWikilinks": True,
                },
            )
            logger.info("Logged to daily note: %s", daily_path)
        except Exception as e:
            logger.warning("Failed to log to daily note: %s", e)
