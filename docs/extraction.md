# Extraction

[< Back to README](../README.md)

## Chunked Extraction

Documents exceeding 680,000 characters (~170K tokens) are split into overlapping chunks for extraction.

### Context budget calculation

| Constant | Value | Rationale |
|----------|-------|-----------|
| `_MODEL_CONTEXT_TOKENS` | 200,000 | Sonnet/Opus/Haiku context window |
| `_RESERVED_TOKENS` | 30,000 | System prompt + user template + output + safety margin |
| `_CHARS_PER_TOKEN` | 4 | Conservative estimate |
| `_MAX_SOURCE_CHARS` | 680,000 | (200K − 30K) × 4 |
| `_CHUNK_OVERLAP_CHARS` | 8,000 | Captures articles straddling chunk boundaries |

### Splitting strategy (`_split_chunks`)

- If the text fits in one chunk, no splitting occurs.
- Otherwise, look for a paragraph break (`\n\n`) within a 2,000-char look-ahead zone near the chunk boundary. Fall back to a line break (`\n`) if no paragraph break is found.
- Each subsequent chunk starts `overlap` characters before the previous chunk ended.
- Guarantees forward progress: `end = max(end, start + 1)`.

### Merge and dedup

- Each chunk is sent to [[CLAUDE]] independently.
- Results are merged, **deduplicated by article reference** (first occurrence wins).
- Metrics are aggregated: summed tokens, summed duration, chunk count recorded.

## EUR-Lex Fetcher

`src/canary/fetchers/eurlex.py` — `EurLexFetcher`

**URL pattern:**
```
https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex_id}
```

**Rate limiting:** 2-second delay between requests (`RATE_LIMIT_DELAY`).

**ETag caching:** In-memory `dict[celex_id → etag]`. On subsequent fetches, sends `If-None-Match` header. HTTP 304 → no content downloaded, returns `(None, False)`.

**Retry:** 5 attempts, exponential backoff (multiplier=1, min=4s, max=60s). Retries on `httpx.TimeoutException` and `httpx.ConnectError`. HTTP 429 → parse `Retry-After` header (default 60s), sleep, then raise to trigger retry.

**HTTP client:**
- Timeouts: connect=10s, read=60s, write=10s, pool=5s
- User-Agent: `CANARY/1.0 regulatory-monitor (github.com/velvetmonkey/canary)`
- `follow_redirects=True`

**HTML → text extraction** (`extract_text`):
- BeautifulSoup with `lxml` backend
- Strips: `nav`, `header`, `footer`, `.EurlexEmbedded`
- Strips inline footnote ref tags (`.oj-note-tag <a>`) that render as `( N )` and break citation matching
- `soup.get_text()` without separator — preserves original whitespace, avoids breaking word splits across `<span>` elements in PDF-to-HTML conversions
