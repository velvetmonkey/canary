"""Tests for fetcher extract_text methods."""

from pathlib import Path

import pytest

from canary.fetchers.eurlex import EurLexFetcher
from canary.fetchers.govinfo import GovInfoFetcher
from canary.fetchers.irishstatute import IrishStatuteFetcher
from canary.fetchers.nzleg import NZLegislationFetcher
from canary.fetchers.ukleg import UKLegislationFetcher

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


class TestUKLegExtractText:
    def test_extracts_from_leg_snippet(self):
        html = """
        <html><body>
            <nav>Navigation</nav>
            <div id="viewLegSnippet">
                <p>An Act to make provision about financial services.</p>
                <p>Section 1: Definitions</p>
            </div>
            <footer>Footer</footer>
        </body></html>
        """
        text = UKLegislationFetcher.extract_text(html)
        assert "financial services" in text
        assert "Section 1" in text
        assert "Navigation" not in text

    def test_empty_html(self):
        text = UKLegislationFetcher.extract_text("<html><body></body></html>")
        assert text.strip() == ""


class TestGovInfoExtractText:
    def test_extracts_from_pre_block(self):
        html = """
        <html><body>
            <h1>Public Law 107-204</h1>
            <pre>
                SARBANES-OXLEY ACT OF 2002
                SEC. 302. CORPORATE RESPONSIBILITY FOR FINANCIAL REPORTS.
            </pre>
        </body></html>
        """
        text = GovInfoFetcher.extract_text(html)
        assert "SARBANES-OXLEY" in text
        assert "SEC. 302" in text

    def test_strips_page_markers(self):
        """[[Page NNN STAT. NNN]] markers should be stripped to prevent citation breakage."""
        html = """
        <html><body><pre>
            No company with a class of securities
            [[Page 116 STAT. 803]]
            or any officer may discharge
        </pre></body></html>
        """
        text = GovInfoFetcher.extract_text(html)
        assert "[[Page" not in text
        assert "STAT." not in text
        assert "securities" in text
        assert "officer" in text

    def test_empty_html(self):
        text = GovInfoFetcher.extract_text("<html><body></body></html>")
        assert text.strip() == ""


class TestNZLegExtractText:
    def test_extracts_from_viewcontent(self):
        html = """
        <html><body>
            <nav>Menu</nav>
            <div id="viewcontent">
                <p>Financial Markets Conduct Act 2013</p>
                <p>Part 1: Preliminary provisions</p>
            </div>
        </body></html>
        """
        text = NZLegislationFetcher.extract_text(html)
        assert "Financial Markets Conduct" in text
        assert "Part 1" in text
        assert "Menu" not in text

    def test_empty_html(self):
        text = NZLegislationFetcher.extract_text("<html><body></body></html>")
        assert text.strip() == ""


class TestIrishStatuteExtractText:
    def test_extracts_from_act_content(self):
        html = """
        <html><body>
            <nav>Navigation</nav>
            <div class="act-content">
                <p>Investment Limited Partnerships (Amendment) Act 2020</p>
                <p>Section 3: Amendment of Act of 1994</p>
            </div>
        </body></html>
        """
        text = IrishStatuteFetcher.extract_text(html)
        assert "Investment Limited Partnerships" in text
        assert "Section 3" in text
        assert "Navigation" not in text

    def test_empty_html(self):
        text = IrishStatuteFetcher.extract_text("<html><body></body></html>")
        assert text.strip() == ""


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
