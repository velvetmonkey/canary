"""New Zealand legislation.govt.nz document fetcher."""

import asyncio
import logging
import time
import warnings

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from canary.fetchers.base import BaseFetcher

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

# NZ legislation: https://www.legislation.govt.nz/act/public/{year}/{number}/latest/whole.html
BASE_URL = "https://www.legislation.govt.nz/{doc_id}/latest/whole.html"
RATE_LIMIT_DELAY = 1.0
USER_AGENT = "CANARY/1.0 regulatory-monitor (github.com/velvetmonkey/canary)"


class NZLegislationFetcher(BaseFetcher):
    """Async fetcher for New Zealand legislation.govt.nz documents."""

    def __init__(self) -> None:
        self._last_request_time = 0.0
        self._etag_cache: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=120, write=10, pool=5),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            await asyncio.sleep(RATE_LIMIT_DELAY - elapsed)
        self._last_request_time = time.monotonic()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def fetch_html(self, doc_id: str) -> tuple[str | None, bool]:
        """Fetch raw HTML for a NZ legislation document.

        doc_id format: act/public/2013/0069, act/public/2021/0030, etc.
        """
        await self._rate_limit()
        client = await self._get_client()
        url = BASE_URL.format(doc_id=doc_id)

        headers: dict[str, str] = {}
        cached_etag = self._etag_cache.get(doc_id)
        if cached_etag:
            headers["If-None-Match"] = cached_etag

        resp = await client.get(url, headers=headers)

        if resp.status_code == 304:
            return None, False

        resp.raise_for_status()

        new_etag = resp.headers.get("ETag")
        if new_etag:
            self._etag_cache[doc_id] = new_etag

        return resp.text, True

    @staticmethod
    def extract_text(html: str) -> str:
        """Extract clean text from NZ legislation HTML."""
        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one("#viewcontent") or soup.select_one(".act") or soup
        for tag in body.find_all(["script", "style", "noscript", "nav"]):
            tag.decompose()
        return body.get_text()

    async def fetch_text(self, doc_id: str) -> tuple[str | None, bool]:
        """Fetch and extract clean text."""
        html, changed = await self.fetch_html(doc_id)
        if html is None:
            return None, False
        text = self.extract_text(html)
        return (text if text and text.strip() else ""), True
