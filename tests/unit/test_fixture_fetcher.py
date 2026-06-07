"""Tests for fixture-backed source fetching."""

import pytest

from canary.fetchers.fixture import FixtureFetcher


@pytest.mark.asyncio
async def test_fixture_fetcher_reads_mapped_sfdr_source(tmp_path):
    fixture_file = tmp_path / "sources" / "sfdr-l1.html"
    fixture_file.parent.mkdir()
    fixture_file.write_text("frozen sfdr source", encoding="utf-8")

    fetcher = FixtureFetcher(tmp_path)

    text, changed = await fetcher.fetch_text("32019R2088")
    assert text == "frozen sfdr source"
    assert changed is True

    text, changed = await fetcher.fetch_text("32019R2088")
    assert text is None
    assert changed is False


@pytest.mark.asyncio
async def test_fixture_fetcher_raises_for_missing_fixture(tmp_path):
    fetcher = FixtureFetcher(tmp_path)

    with pytest.raises(FileNotFoundError):
        await fetcher.fetch_text("missing")
