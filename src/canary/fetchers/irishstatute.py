"""Irish Statute Book (irishstatutebook.ie) document fetcher."""

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

# Irish Statute Book: https://www.irishstatutebook.ie/eli/{year}/act/{number}/enacted/en/html
BASE_URL = "https://www.irishstatutebook.ie/eli/{doc_id}/enacted/en/html"
RATE_LIMIT_DELAY = 1.0
USER_AGENT = "CANARY/1.0 regulatory-monitor (github.com/velvetmonkey/canary)"


class IrishStatuteFetcher(BaseFetcher):
    """Async fetcher for Irish Statute Book documents."""

    def __init__(self) -> None:
        self._last_request_time = 0.0
        self._etag_cache: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10, read=60, write=10, pool=5),
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
        """Fetch raw HTML for an Irish statute.

        doc_id format: 2023/act/48, 2024/act/6, etc.
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
        """Extract clean text from Irish Statute Book HTML."""
        soup = BeautifulSoup(html, "lxml")
        body = soup.select_one(".act-content") or soup.select_one("body")
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
