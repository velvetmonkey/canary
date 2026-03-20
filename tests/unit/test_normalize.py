"""Tests for shared text normalization."""

from canary.analysis.normalize import citation_matches, normalize_for_matching


class TestNormalizeForMatching:
    def test_smart_single_quotes(self):
        assert normalize_for_matching("\u2018hello\u2019") == "'hello'"

    def test_smart_double_quotes(self):
        assert normalize_for_matching("\u201Chello\u201D") == '"hello"'

    def test_guillemets(self):
        assert normalize_for_matching("\u00ABhello\u00BB") == '"hello"'

    def test_nbsp_collapsed(self):
        # NFKC converts NBSP (U+00A0) to regular space, then whitespace collapse
        assert normalize_for_matching("hello\u00A0world") == "hello world"

    def test_en_dash(self):
        assert normalize_for_matching("2019\u20132024") == "2019-2024"

    def test_em_dash(self):
        assert normalize_for_matching("foo\u2014bar") == "foo-bar"

    def test_non_breaking_hyphen(self):
        assert normalize_for_matching("non\u2011breaking") == "non-breaking"

    def test_figure_dash(self):
        assert normalize_for_matching("figure\u2012dash") == "figure-dash"

    def test_math_minus(self):
        assert normalize_for_matching("a\u2212b") == "a-b"

    def test_ligature_fi(self):
        # NFKC decomposes fi ligature (U+FB01)
        assert normalize_for_matching("\uFB01nancial") == "financial"

    def test_whitespace_collapse(self):
        assert normalize_for_matching("  hello   world  ") == "hello world"

    def test_lowercase(self):
        assert normalize_for_matching("HELLO World") == "hello world"

    def test_soft_hyphen_stripped(self):
        # U+00AD is an invisible hyphenation hint — must not break matching
        assert normalize_for_matching("sus\u00ADtain\u00ADabil\u00ADity") == "sustainability"

    def test_zero_width_space_stripped(self):
        assert normalize_for_matching("hello\u200Bworld") == "helloworld"

    def test_zero_width_non_joiner_stripped(self):
        assert normalize_for_matching("hello\u200Cworld") == "helloworld"

    def test_bom_stripped(self):
        assert normalize_for_matching("\uFEFFhello") == "hello"

    def test_word_joiner_stripped(self):
        assert normalize_for_matching("hello\u2060world") == "helloworld"

    def test_prime_to_apostrophe(self):
        assert normalize_for_matching("Article 8\u2032") == "article 8'"

    def test_ellipsis_expanded(self):
        # NFKC handles this one
        assert normalize_for_matching("etc\u2026") == "etc..."

    def test_combined_eurlex_scenario(self):
        """EUR-Lex source text with smart quotes, NBSP, and en-dash."""
        source = (
            "\u201Cfinancial\u00A0products shall\u00A0disclose "
            "sustainability risks\u201D\u2014Article\u00A08"
        )
        query = '"financial products shall disclose sustainability risks"-Article 8'
        norm_source = normalize_for_matching(source)
        norm_query = normalize_for_matching(query)
        assert norm_query in norm_source


class TestCitationMatches:
    def test_exact_match(self):
        assert citation_matches("financial products shall disclose", "financial products shall disclose")

    def test_exact_match_in_longer_source(self):
        assert citation_matches("shall disclose", "Article 8 requires financial products shall disclose risks.")

    def test_no_match(self):
        assert not citation_matches("this does not exist", "Article 8 requires disclosure.")

    def test_prefix_match_with_ellipsis(self):
        source = "financial market participants shall integrate sustainability risks in investment decision-making processes and disclose them to investors"
        # Claude truncated with ...
        quote = "financial market participants shall integrate sustainability risks in investment decision-making processes..."
        assert citation_matches(quote, source)

    def test_prefix_match_cut_short(self):
        source = "financial market participants shall integrate sustainability risks in investment decision-making processes and disclose them to investors"
        # Claude just stopped quoting
        quote = "financial market participants shall integrate sustainability risks in investment decision-making processes"
        assert citation_matches(quote, source)

    def test_prefix_too_short_rejected(self):
        # Under 80 chars — prefix match should not rescue a quote that doesn't substring-match
        source = "financial products shall disclose sustainability risks to all investors"
        # This quote has extra words not in source, AND is short — should fail
        quote = "financial products shall disclose the full extent of their..."
        assert not citation_matches(quote, source)

    def test_unicode_normalization_with_prefix(self):
        source = "\u201Cfinancial market participants shall integrate sustainability risks in investment decision-making\u201D"
        quote = '"financial market participants shall integrate sustainability risks in investment decision-making...'
        assert citation_matches(quote, source)

    def test_footnote_markers_stripped(self):
        source = "of the European Parliament and of the Council*8, Directive 2014/65/EU"
        quote = "of the European Parliament and of the Council, Directive 2014/65/EU"
        assert citation_matches(quote, source)

    def test_elision_match(self):
        source = "financial market participants shall integrate sustainability risks in their investment decisions and disclose those risks to end investors in a clear manner"
        quote = "financial market participants shall integrate sustainability risks [...] and disclose those risks to end investors in a clear manner"
        assert citation_matches(quote, source)

    def test_elision_wrong_order_rejected(self):
        source = "AAA BBB CCC DDD EEE FFF GGG HHH III JJJ KKK"
        quote = "EEE FFF GGG HHH III JJJ KKK [...] AAA BBB CCC DDD"
        assert not citation_matches(quote, source)

    def test_elision_bare_dots(self):
        """Bare ... (no brackets) should also trigger elision matching."""
        source = "financial market participants shall integrate sustainability risks in their investment decisions and disclose those risks to end investors in a clear manner"
        quote = "financial market participants shall integrate sustainability risks... and disclose those risks to end investors in a clear manner"
        assert citation_matches(quote, source)

    def test_elision_segment_too_short_rejected(self):
        source = "financial market participants shall integrate sustainability risks in investment decisions"
        # One segment under 40 chars — elision match should not kick in
        quote = "financial market participants [...] in investment decisions"
        assert not citation_matches(quote, source)
