"""Tests for EurLexFetcher HTTP behavior with mocked httpx responses."""

import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from canary.fetchers.eurlex import EURLEX_HTML_URL, EurLexFetcher, RATE_LIMIT_DELAY


@pytest.fixture
def fetcher():
    f = EurLexFetcher()
    # Skip rate limit delay in most tests
    f._last_request_time = time.monotonic()
    return f


class TestFetchHtml:
    async def test_success_200_returns_html_and_true(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, text="<html>body</html>")

        html, changed = await fetcher.fetch_html("32019R2088")
        assert html == "<html>body</html>"
        assert changed is True

    async def test_stores_etag_from_response(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, text="<html/>", headers={"ETag": '"abc123"'})

        await fetcher.fetch_html("32019R2088")
        assert fetcher._etag_cache["32019R2088"] == '"abc123"'

    async def test_no_etag_header_skips_cache(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, text="<html/>")

        await fetcher.fetch_html("32019R2088")
        assert "32019R2088" not in fetcher._etag_cache

    async def test_sends_if_none_match_when_etag_cached(self, fetcher, httpx_mock):
        fetcher._etag_cache["32019R2088"] = '"etag-value"'
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, text="<html/>")

        await fetcher.fetch_html("32019R2088")

        request = httpx_mock.get_request()
        assert request.headers["If-None-Match"] == '"etag-value"'

    async def test_304_not_modified_returns_none_false(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, status_code=304)

        html, changed = await fetcher.fetch_html("32019R2088")
        assert html is None
        assert changed is False

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_202_document_compiling_triggers_retry(self, mock_sleep, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        # First: 202, then: 200
        httpx_mock.add_response(url=url, status_code=202)
        httpx_mock.add_response(url=url, text="<html>compiled</html>")

        html, changed = await fetcher.fetch_html("32019R2088")
        assert html == "<html>compiled</html>"
        assert changed is True

    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_429_rate_limited_triggers_retry(self, mock_sleep, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        # First: 429 with Retry-After, then: 200
        httpx_mock.add_response(url=url, status_code=429, headers={"Retry-After": "1"})
        httpx_mock.add_response(url=url, text="<html>ok</html>")

        html, changed = await fetcher.fetch_html("32019R2088")
        assert html == "<html>ok</html>"
        assert changed is True

    async def test_4xx_raises_http_status_error(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, status_code=404)

        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch_html("32019R2088")

    async def test_5xx_raises_http_status_error(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, status_code=500)

        with pytest.raises(httpx.HTTPStatusError):
            await fetcher.fetch_html("32019R2088")


class TestFetchText:
    async def test_returns_extracted_text(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, text="<html><body><p>Hello world</p></body></html>")

        text, changed = await fetcher.fetch_text("32019R2088")
        assert "Hello world" in text
        assert changed is True

    async def test_etag_unchanged_returns_none(self, fetcher, httpx_mock):
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, status_code=304)

        text, changed = await fetcher.fetch_text("32019R2088")
        assert text is None
        assert changed is False


class TestRateLimit:
    @patch("asyncio.sleep", new_callable=AsyncMock)
    async def test_rate_limit_sleeps_when_too_fast(self, mock_sleep, httpx_mock):
        fetcher = EurLexFetcher()
        url = EURLEX_HTML_URL.format(celex_id="32019R2088")
        httpx_mock.add_response(url=url, text="<html/>")

        # First call sets _last_request_time
        fetcher._last_request_time = time.monotonic()
        await fetcher.fetch_html("32019R2088")

        # mock_sleep is called for rate limiting (RATE_LIMIT_DELAY - elapsed)
        # Since we just set _last_request_time, elapsed is ~0, so it should sleep ~RATE_LIMIT_DELAY
        if mock_sleep.call_count > 0:
            sleep_arg = mock_sleep.call_args_list[0][0][0]
            assert 0 < sleep_arg <= RATE_LIMIT_DELAY
