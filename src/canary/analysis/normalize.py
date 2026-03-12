"""Shared text normalization for citation matching."""

import re
import unicodedata

# Smart quotes → ASCII
_QUOTE_TABLE = str.maketrans({
    "\u2018": "'",   # left single
    "\u2019": "'",   # right single
    "\u201C": '"',   # left double
    "\u201D": '"',   # right double
    "\u00AB": '"',   # left guillemet
    "\u00BB": '"',   # right guillemet
    "\u2032": "'",   # prime → apostrophe
})

# Various dashes → ASCII hyphen
_DASH_RE = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2212]")

# Invisible characters that survive NFKC — strip them entirely
_INVISIBLE_RE = re.compile(r"[\u00AD\u200B\u200C\u200D\uFEFF\u2060]")

# Inline footnote markers: *1, *8, *14 etc. (EUR-Lex proposal documents)
_FOOTNOTE_MARKER_RE = re.compile(r"\*\d{1,3}")

# Editorial elision marks: [...] or [… ] — used by Claude to skip text mid-quote
_ELISION_RE = re.compile(r"\s*\[\.{3}\]\s*|\s*\[\u2026\]\s*")


def normalize_for_matching(text: str) -> str:
    """Normalize text for fuzzy citation matching.

    - NFKC (handles NBSP, ligatures, width variants, ellipsis)
    - Strip invisible chars (soft hyphen, zero-width spaces, BOM, word joiner)
    - Smart quotes + prime → ASCII
    - Dashes → ASCII hyphen
    - Whitespace collapse + lowercase
    """
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text)
    text = text.translate(_QUOTE_TABLE)
    text = _DASH_RE.sub("-", text)
    text = _FOOTNOTE_MARKER_RE.sub("", text)
    return " ".join(text.split()).lower()


# Minimum prefix length (chars) for prefix matching to count as verified.
# Short enough to tolerate truncation, long enough to avoid false positives.
_MIN_PREFIX_LEN = 80


def citation_matches(quote: str, source: str) -> bool:
    """Check if a quote matches the source text.

    Strategies (in order):
    1. Exact normalized substring
    2. Prefix match (for quotes truncated with '...' or cut short)
    3. Elision match (for quotes with [...] skipping mid-text)
    """
    nq = normalize_for_matching(quote.rstrip(".").rstrip())
    ns = normalize_for_matching(source)

    # Exact substring
    if nq in ns:
        return True

    # Quote-insensitive match — unify single/double ASCII quotes
    # Legal text uses quotes stylistically; Claude sometimes swaps them
    nq_noquote = nq.replace('"', "'")
    ns_noquote = ns.replace('"', "'")
    if nq_noquote in ns_noquote:
        return True

    # Prefix match — strip trailing ellipsis then check
    prefix = nq.rstrip(".")
    if len(prefix) >= _MIN_PREFIX_LEN and prefix in ns:
        return True

    # Quote-insensitive prefix match
    prefix_nq = nq_noquote.rstrip(".")
    if len(prefix_nq) >= _MIN_PREFIX_LEN and prefix_nq in ns_noquote:
        return True

    # Elision match — quote contains [...] to skip source text
    # Split on elision marks and verify each segment exists in order
    segments = _ELISION_RE.split(nq)
    segments = [s.strip().rstrip(".").strip() for s in segments if s.strip()]
    if len(segments) >= 2 and all(len(s) >= 40 for s in segments):
        pos = 0
        for seg in segments:
            idx = ns.find(seg, pos)
            if idx == -1:
                break
            pos = idx + len(seg)
        else:
            return True

    return False
