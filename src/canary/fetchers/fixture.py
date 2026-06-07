"""Filesystem-backed fetcher for deterministic demo runs."""

from pathlib import Path

from canary.fetchers.base import BaseFetcher


DEFAULT_FIXTURE_NAMES = {
    "32019R2088": "sfdr-l1",
}


class FixtureFetcher(BaseFetcher):
    """Read pre-fetched source text from a fixture directory."""

    def __init__(self, fixture_dir: str | Path) -> None:
        self._fixture_dir = Path(fixture_dir).expanduser()
        self._seen: set[str] = set()

    async def fetch_text(self, document_id: str) -> tuple[str | None, bool]:
        """Fetch source text from disk.

        The fixture file is expected to contain the exact text that a live
        fetcher's fetch_text() would have returned.
        """
        if document_id in self._seen:
            return None, False

        path = self._find_fixture(document_id)
        text = path.read_text(encoding="utf-8")
        self._seen.add(document_id)
        return text, True

    async def close(self) -> None:
        """No resources to release."""

    def _find_fixture(self, document_id: str) -> Path:
        stem = DEFAULT_FIXTURE_NAMES.get(document_id, document_id)
        candidates = [
            self._fixture_dir / "sources" / f"{stem}.html",
            self._fixture_dir / "sources" / f"{stem}.txt",
            self._fixture_dir / "sources" / f"{document_id}.html",
            self._fixture_dir / "sources" / f"{document_id}.txt",
            self._fixture_dir / f"{stem}.html",
            self._fixture_dir / f"{stem}.txt",
            self._fixture_dir / f"{document_id}.html",
            self._fixture_dir / f"{document_id}.txt",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        searched = ", ".join(str(candidate) for candidate in candidates)
        raise FileNotFoundError(f"No fixture for {document_id!r}; searched: {searched}")
