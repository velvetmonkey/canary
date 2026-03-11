"""Base fetcher interface for regulatory document sources."""

from abc import ABC, abstractmethod


class BaseFetcher(ABC):
    """Abstract base class for document fetchers."""

    @abstractmethod
    async def fetch_text(self, document_id: str) -> tuple[str | None, bool]:
        """Fetch and extract clean text for a document.

        Returns (text, changed). If unchanged, returns (None, False).
        """

    @abstractmethod
    async def close(self) -> None:
        """Release any resources held by the fetcher."""
