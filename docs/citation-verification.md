# Citation Verification

[< Back to README](../README.md)

## How It Works

Every quote extracted by [[CLAUDE]] is mechanically verified against the source text. The verification [[Pipelines|pipeline]] in `src/canary/analysis/normalize.py` applies 5 strategies in order, stopping at the first match:

1. **Exact normalized match** — normalized quote is a substring of normalized source.
2. **Quote-insensitive match** — swap all quote characters (`"` ↔ `'`) and retry. Legal text varies between single and double quotes across consolidations.
3. **Prefix match** — if the quote is ≥80 characters, strip trailing `.` and check if the prefix exists. Handles Claude's tendency to truncate long quotes with `...`.
4. **Quote-insensitive prefix match** — combination of (2) and (3).
5. **Elision match** — split on `[...]` or `[…]`, verify each segment (≥40 chars) exists in the source in order. Handles quotes with internal omissions.

## Unicode Normalization

`normalize_for_matching` is applied before all matching:

| Transform | Examples |
|-----------|----------|
| NFKC normalization | NBSP (U+00A0) → space, fi ligature (U+FB01) → `fi` |
| Smart quotes → ASCII | `\u2018\u2019` → `'`, `\u201C\u201D` → `"`, guillemets → `"` |
| Dashes → hyphen | en-dash, em-dash, figure dash, minus sign → `-` |
| Invisible chars stripped | soft hyphen, zero-width space, ZWNJ, BOM, word joiner |
| Footnote markers stripped | `*1`, `*14` etc. (EUR-Lex proposal inline markers) |
| Whitespace collapsed | runs of whitespace → single space |
| Lowercased | case-insensitive comparison |

## Re-Quote Pipeline

When citation verification fails, CANARY automatically attempts to repair the quote.

`requote_citations()` in `src/canary/analysis/objectives.py`:

1. Collect all objectives with unverified `verbatim_quote` fields.
2. Format them into a prompt listing the article, title, obligation type, who, what, and the first 200 chars of the original quote.
3. Send the full source text + formatted list to Claude with instructions to find the **exact passage** that establishes each obligation.
4. Claude returns a `RequoteResult` with corrected objectives.
5. For each corrected quote, re-run citation verification. If it now passes, replace the original.
6. Log: `"Re-quoted N/M citations (XXms, I/O tokens)"`.

Retry: 2 attempts, exponential backoff (4–60s). Output tokens: `min(max(len(objectives) * 400 + 2000, 4096), 16384)`.
