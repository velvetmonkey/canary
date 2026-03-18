"""UK legislation.gov.uk document fetcher."""

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

# legislation.gov.uk serves full text at /{type}/{year}/{number}/enacted (or /made)
# Document IDs follow the pattern: ukpga/2023/30, uksi/2023/1206, etc.
BASE_URL = "https://www.legislation.gov.uk/{doc_id}/enacted"
RATE_LIMIT_DELAY = 1.0
USER_AGENT = "CANARY/1.0 regulatory-monitor (github.com/velvetmonkey/canary)"

# Tags/classes to strip from legislation.gov.uk HTML
STRIP_SELECTORS = [
    "nav", "header", "footer",
    "#content-notice", ".LegClearFix",
    "#skipLinks", ".breadcrumb",
    "#layout1", "#layout2",  # sidebar/chrome
    ".LegSnippet",  # "more resources" boxes
]


class UKLegislationFetcher(BaseFetcher):
    """Async fetcher for UK legislation.gov.uk documents."""

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
        """Fetch raw HTML for a UK legislation document ID.

        doc_id format: ukpga/2023/30, uksi/2023/1206, etc.
        Returns (html_content, changed). If ETag matches, returns (None, False).
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
            logger.info("ETag match for %s — no change", doc_id)
            return None, False

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "30"))
            logger.warning("Rate limited on %s, waiting %ds", doc_id, retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.TimeoutException(f"Rate limited: {doc_id}")

        resp.raise_for_status()

        new_etag = resp.headers.get("ETag")
        if new_etag:
            self._etag_cache[doc_id] = new_etag

        return resp.text, True

    @staticmethod
    def extract_text(html: str) -> str:
        """Extract clean text from legislation.gov.uk HTML."""
        soup = BeautifulSoup(html, "lxml")
        # Extract the legislation body first, before stripping anything
        body = soup.select_one("#viewLegSnippet") or soup.select_one(".LegContent") or soup
        # Remove script/style/nav chrome from the selected body
        for tag in body.find_all(["script", "style", "noscript"]):
            tag.decompose()
        for selector in STRIP_SELECTORS:
            for tag in body.select(selector):
                tag.decompose()
        return body.get_text()

    async def fetch_text(self, doc_id: str) -> tuple[str | None, bool]:
        """Fetch and extract clean text for a UK legislation document.

        Returns (text, changed). If unchanged via ETag, returns (None, False).
        """
        html, changed = await self.fetch_html(doc_id)
        if html is None:
            return None, False
        text = self.extract_text(html)
        if not text or not text.strip():
            return "", True
        return text, True
