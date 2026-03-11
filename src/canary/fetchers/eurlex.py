"""EUR-Lex document fetcher with rate limiting, retry, and ETag caching."""

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

EURLEX_HTML_URL = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex_id}"
RATE_LIMIT_DELAY = 2.0
USER_AGENT = "CANARY/1.0 regulatory-monitor (github.com/velvetmonkey/canary)"

# Tags/classes to strip from EUR-Lex HTML
STRIP_SELECTORS = ["nav", "header", "footer", ".EurlexEmbedded"]


class EurLexFetcher(BaseFetcher):
    """Async fetcher for EUR-Lex documents with rate limiting and ETag caching."""

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
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def fetch_html(self, celex_id: str) -> tuple[str | None, bool]:
        """Fetch raw HTML for a CELEX ID.

        Returns (html_content, changed). If ETag matches, returns (None, False).
        """
        await self._rate_limit()
        client = await self._get_client()
        url = EURLEX_HTML_URL.format(celex_id=celex_id)

        headers: dict[str, str] = {}
        cached_etag = self._etag_cache.get(celex_id)
        if cached_etag:
            headers["If-None-Match"] = cached_etag

        resp = await client.get(url, headers=headers)

        if resp.status_code == 304:
            logger.info("ETag match for %s — no change", celex_id)
            return None, False

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("Rate limited on %s, waiting %ds", celex_id, retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.TimeoutException(f"Rate limited: {celex_id}")

        resp.raise_for_status()

        new_etag = resp.headers.get("ETag")
        if new_etag:
            self._etag_cache[celex_id] = new_etag

        return resp.text, True

    @staticmethod
    def extract_text(html: str) -> str:
        """Extract clean text from EUR-Lex HTML, stripping navigation and chrome."""
        soup = BeautifulSoup(html, "lxml")
        for selector in STRIP_SELECTORS:
            for tag in soup.select(selector):
                tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    async def fetch_text(self, celex_id: str) -> tuple[str | None, bool]:
        """Fetch and extract clean text for a CELEX ID.

        Returns (text, changed). If unchanged via ETag, returns (None, False).
        """
        html, changed = await self.fetch_html(celex_id)
        if html is None:
            return None, False
        return self.extract_text(html), True
