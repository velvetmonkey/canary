"""Tests for vault writer with mocked MCP tools."""

from unittest.mock import AsyncMock

import pytest

from canary.output.vault import VaultWriter


class TestVaultWriter:
    async def test_call_tool_raises_for_unknown(self):
        writer = VaultWriter()
        writer._tools = {"search": AsyncMock()}
        try:
            await writer._call_tool("nonexistent", {})
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "nonexistent" in str(e)
            assert "search" in str(e)

    async def test_call_tool_invokes_correct_tool(self):
        mock_tool = AsyncMock(return_value="result")
        writer = VaultWriter()
        writer._tools = {"search": mock_tool}

        await writer._call_tool("search", {"query": "test"})
        mock_tool.ainvoke.assert_called_once_with({"query": "test"})

    async def test_check_duplicate_returns_false_when_no_results(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={"results": []})
        writer._tools = {"search": mock_search}

        assert await writer.check_duplicate("run-001") is False

    async def test_check_duplicate_returns_true_when_found(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={"results": [{"path": "report.md"}]})
        writer._tools = {"search": mock_search}

        assert await writer.check_duplicate("run-001") is True

    async def test_check_duplicate_returns_false_on_error(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(side_effect=Exception("connection error"))
        writer._tools = {"search": mock_search}

        assert await writer.check_duplicate("run-001") is False

    async def test_write_report_skips_duplicate(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={"results": [{"path": "existing.md"}]})
        writer._tools = {"search": mock_search, "vault_create_note": AsyncMock()}

        result = await writer.write_report("# Report", "SFDR-L1", "run-dup")
        assert result is None

    async def test_write_report_creates_note(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={"results": []})
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"search": mock_search, "vault_create_note": mock_create}

        result = await writer.write_report("# Report", "SFDR-L1", "run-new")
        assert result is not None
        assert "SFDR-L1" in result
        mock_create.ainvoke.assert_called_once()

    async def test_write_report_returns_none_on_error(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={"results": []})
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(side_effect=Exception("write failed"))
        writer._tools = {"search": mock_search, "vault_create_note": mock_create}

        result = await writer.write_report("# Report", "SFDR-L1", "run-err")
        assert result is None

    async def test_log_to_daily_calls_add_to_section(self):
        writer = VaultWriter()
        mock_add = AsyncMock()
        mock_add.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"vault_add_to_section": mock_add}

        await writer.log_to_daily("CANARY detected 1 change")
        mock_add.ainvoke.assert_called_once()
        call_args = mock_add.ainvoke.call_args[0][0]
        assert call_args["section"] == "Log"
        assert "CANARY detected" in call_args["content"]

    async def test_log_to_daily_handles_error(self):
        writer = VaultWriter()
        mock_add = AsyncMock()
        mock_add.ainvoke = AsyncMock(side_effect=Exception("daily note missing"))
        writer._tools = {"vault_add_to_section": mock_add}

        # Should not raise
        await writer.log_to_daily("test message")

    async def test_disconnect_clears_state(self):
        writer = VaultWriter()
        writer._client = "something"
        writer._tools = {"a": "b"}

        await writer.disconnect()
        assert writer._client is None
        assert writer._tools == {}

    async def test_write_objective_sanitizes_article_ref(self):
        """Verify article refs with parens/spaces are sanitized for filenames."""
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={"results": []})
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"search": mock_search, "vault_create_note": mock_create}

        path = await writer.write_objective("# Note", "Article 4(1)(a)", "sfdr-l1")
        assert path is not None
        assert "article-4-1-a" in path
        assert "(" not in path
        assert " " not in path

    async def test_write_objective_complex_article_ref(self):
        """Edge case: deeply nested article reference."""
        writer = VaultWriter()
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"vault_create_note": mock_create}

        path = await writer.write_objective("# Note", "Article 8(2)(b)(iii)", "sfdr-l1")
        assert path is not None
        assert "article-8-2-b-iii" in path
        # No double dashes or trailing dashes
        assert "--" not in path
        assert not path.endswith("-")

    async def test_write_objective_passes_overwrite_and_wikilinks(self):
        """Vault writer must pass overwrite=True and suggestOutgoingLinks=True."""
        writer = VaultWriter()
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"vault_create_note": mock_create}

        await writer.write_objective("# Note", "Article 3", "sfdr-l1")
        call_args = mock_create.ainvoke.call_args[0][0]
        assert call_args["overwrite"] is True
        assert call_args["suggestOutgoingLinks"] is True

    async def test_write_objective_simple_article(self):
        """Simple article ref without parens."""
        writer = VaultWriter()
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"vault_create_note": mock_create}

        path = await writer.write_objective("# Note", "Article 3", "sfdr-l1")
        assert path is not None
        assert "article-3" in path

    async def test_write_readme_creates_note(self):
        writer = VaultWriter()
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(return_value=None)
        writer._tools = {"vault_create_note": mock_create}

        readme = "---\ntype: regulation-index\n---\n\n# SFDR"
        path = await writer.write_readme(readme, "work/compliance/objectives/sfdr/README.md")
        assert path == "work/compliance/objectives/sfdr/README.md"
        call_args = mock_create.ainvoke.call_args[0][0]
        assert call_args["overwrite"] is True
        assert call_args["frontmatter"]["type"] == "regulation-index"
        assert "# SFDR" in call_args["content"]

    async def test_write_readme_returns_none_on_error(self):
        writer = VaultWriter()
        mock_create = AsyncMock()
        mock_create.ainvoke = AsyncMock(side_effect=Exception("write failed"))
        writer._tools = {"vault_create_note": mock_create}

        result = await writer.write_readme("# README", "some/path.md")
        assert result is None

    async def test_search_by_type_returns_list(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value={
            "notes": [
                {"path": "a.md", "frontmatter": {"type": "regulation-index"}},
                {"path": "b.md", "frontmatter": {"type": "regulation-index"}},
            ]
        })
        writer._tools = {"search": mock_search}

        results = await writer.search_by_type("regulation-index")
        assert len(results) == 2
        assert results[0]["path"] == "a.md"

    async def test_search_by_type_handles_json_string(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(return_value='[{"path": "c.md"}]')
        writer._tools = {"search": mock_search}

        results = await writer.search_by_type("regulation-index")
        assert len(results) == 1

    async def test_search_by_type_handles_error(self):
        writer = VaultWriter()
        mock_search = AsyncMock()
        mock_search.ainvoke = AsyncMock(side_effect=Exception("search failed"))
        writer._tools = {"search": mock_search}

        with pytest.raises(Exception):
            await writer.search_by_type("regulation-index")
