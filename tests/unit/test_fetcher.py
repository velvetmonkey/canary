"""Tests for EUR-Lex fetcher."""

from pathlib import Path

import pytest

from canary.fetchers.eurlex import EurLexFetcher

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "sfdr_l1.html"


class TestExtractText:
    def test_extracts_text_from_html(self):
        html = FIXTURE_PATH.read_text()
        text = EurLexFetcher.extract_text(html)
        assert len(text) > 1000
        # SFDR should contain regulation references
        assert "2019/2088" in text or "sustainable" in text.lower()

    def test_strips_nav_and_chrome(self):
        html = """
        <html>
        <body>
            <nav>Navigation</nav>
            <header>Header</header>
            <div class="EurlexEmbedded">Embedded</div>
            <div>Real content about Article 8</div>
            <footer>Footer</footer>
        </body>
        </html>
        """
        text = EurLexFetcher.extract_text(html)
        assert "Navigation" not in text
        assert "Header" not in text
        assert "Embedded" not in text
        assert "Footer" not in text
        assert "Article 8" in text

    def test_strips_footnote_references(self):
        """Inline footnote markers like (14) from <span class="oj-note-tag"> must be removed."""
        html = """
        <html>
        <body>
            <p>of the European Parliament and of the Council
            <a id="ntc14" href="#ntr14">(<span class="oj-super oj-note-tag">14</span>)</a>;
            brief summaries</p>
        </body>
        </html>
        """
        text = EurLexFetcher.extract_text(html)
        assert "( 14 )" not in text
        assert "(14)" not in text
        assert "Council" in text
        assert "brief summaries" in text

    def test_empty_html(self):
        text = EurLexFetcher.extract_text("<html><body></body></html>")
        assert text == "" or text.strip() == ""


@pytest.mark.integration
async def test_fetch_live_eurlex():
    """Integration test: fetch real SFDR L1 from EUR-Lex."""
    fetcher = EurLexFetcher()
    try:
        text, changed = await fetcher.fetch_text("32019R2088")
        assert text is not None
        assert len(text) > 5000
        assert "2019/2088" in text or "sustainable" in text.lower()
    finally:
        await fetcher.close()
