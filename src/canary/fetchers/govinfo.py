"""US GovInfo (govinfo.gov) document fetcher for public laws and compilations."""

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

# GovInfo serves public laws at: /content/pkg/{PLAW-NNNpublNNN}/html/{PLAW-NNNpublNNN}.htm
# and compilations at: /content/pkg/{COMPS-NNNN}/html/{COMPS-NNNN}.htm
BASE_URL = "https://www.govinfo.gov/content/pkg/{doc_id}/html/{doc_id}.htm"
RATE_LIMIT_DELAY = 1.0
USER_AGENT = "CANARY/1.0 regulatory-monitor (github.com/velvetmonkey/canary)"


class GovInfoFetcher(BaseFetcher):
    """Async fetcher for US GovInfo public laws and compilations."""

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
        """Fetch raw HTML for a GovInfo document.

        doc_id format: PLAW-107publ204, PLAW-111publ203, COMPS-1879, etc.
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
        """Extract clean text from GovInfo HTML.

        GovInfo public law pages use <pre> blocks for the law text.
        """
        soup = BeautifulSoup(html, "lxml")
        # GovInfo wraps law text in <pre> tags
        body = soup.select_one("pre") or soup.select_one("body")
        for tag in body.find_all(["script", "style", "noscript"]):
            tag.decompose()
        return body.get_text()

    async def fetch_text(self, doc_id: str) -> tuple[str | None, bool]:
        """Fetch and extract clean text."""
        html, changed = await self.fetch_html(doc_id)
        if html is None:
            return None, False
        text = self.extract_text(html)
        return (text if text and text.strip() else ""), True
