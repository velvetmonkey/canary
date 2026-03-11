"""Tests for vault writer with mocked MCP tools."""

from unittest.mock import AsyncMock

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
