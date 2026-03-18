# CANARY

**C**ompliance **AN**alysis and **A**utomated **R**egulatory **Y**ield

Continuous monitoring of financial regulation across 5 jurisdictions — fetch changes, extract obligations, verify every citation, deliver audit-ready reports with cross-linked knowledge graph.

## Table of Contents

- [Data Sources](#data-sources)
- [Extraction Output](#extraction-output)
- [Part 1 — For Everyone](#part-1--for-everyone)
  - [The Problem](#the-problem)
  - [What CANARY Does](#what-canary-does)
  - [Manual Process vs CANARY](#manual-process-vs-canary)
  - [Guarantees and Trust Model](#guarantees-and-trust-model)
  - [The Wider Lifecycle](#the-wider-lifecycle)
- [Part 2 — Technical Deep Dive](#part-2--technical-deep-dive)
  - [Architecture Overview](#architecture-overview)
  - [Pipeline Nodes](#pipeline-nodes)
  - [LangGraph State](#langgraph-state)
  - [Pydantic Data Models](#pydantic-data-models)
  - [Citation Verification](#citation-verification)
  - [Chunked Extraction](#chunked-extraction)
  - [Re-Quote Pipeline](#re-quote-pipeline)
  - [EUR-Lex Fetcher](#eur-lex-fetcher)
  - [SQLite Storage](#sqlite-storage)
  - [Vault Integration](#vault-integration)
  - [Observability](#observability)
- [Part 3 — Operations](#part-3--operations)
  - [Quick Start](#quick-start)
  - [Commands](#commands)
  - [Configuration](#configuration)
  - [Vault Output Structure](#vault-output-structure)
  - [Output Formats](#output-formats)
  - [Testing](#testing)
  - [Dependencies](#dependencies)
  - [Design Philosophy](#design-philosophy)
  - [Currently Monitored Sources](#currently-monitored-sources)
  - [Roadmap / Phase 2](#roadmap--phase-2)
- [Independent Code Review (Grok)](#independent-code-review-grok)
  - [Product Assessment](#product-assessment)
  - [Code Assessment](#code-assessment)
- [License](#license)

### Data Sources

| Fetcher | Jurisdiction | Source | URL pattern |
|---------|-------------|--------|-------------|
| `eurlex` | EU | EUR-Lex | `eur-lex.europa.eu` |
| `ukleg` | UK | UK Legislation | `legislation.gov.uk` |
| `govinfo` | US | US GovInfo | `govinfo.gov` |
| `nzleg` | NZ | NZ Legislation | `legislation.govt.nz` |
| `irishstatute` | IE | Irish Statute Book | `irishstatutebook.ie` |

### Extraction Output

> **See [`output/`](output/) for real extraction output** — 453 compliance objectives across 14 regulations in 5 jurisdictions, each with verified citations and cross-linked wikilinks.

| Source | Regulation | Objectives |
|--------|-----------|-----------|
| `SFDR-L1` | SFDR Level 1 — Reg (EU) 2019/2088 | 35 |
| `SFDR-RTS` | SFDR RTS — Delegated Reg (EU) 2022/1288 | 112 |
| `SFDR-2-PROPOSAL` | SFDR 2.0 Amendment Proposal (Nov 2025) | 123 |
| `EU-TAXONOMY` | EU Taxonomy Regulation (EU) 2020/852 | 54 |
| `MIFID-SUSTAINABILITY` | MiFID II Sustainability Preferences | 44 |
| `UK-FSA-2023` | UK Financial Services and Markets Act 2023 | 5 |
| `UK-TCFD-REGS` | UK Climate-Related Financial Disclosures Regs 2022 | 10 |
| `UK-SDR-REGS` | UK Sustainability Disclosure Requirements Regs 2023 | 10 |
| `UK-CLIMATE-CHANGE` | UK Climate Change Act 2008 | 10 |
| `UK-ENV-ACT` | UK Environment Act 2021 | 10 |
| `US-SOX` | US Sarbanes-Oxley Act 2002 | 10 |
| `NZ-FMC-ACT` | NZ Financial Markets Conduct Act 2013 | 20 |
| `IE-COMPANIES-ACT` | Irish Companies Act 2014 | 10 |

---

## Part 1 — For Everyone

### The Problem

EU sustainable finance regulation is a moving target. SFDR, the Taxonomy Regulation, MiFID II sustainability amendments, CSRD — each carries disclosure obligations, and each is periodically amended, recast, or supplemented by delegated acts. Regulatory text is published on EUR-Lex, often without advance notice, and a single missed amendment can leave a firm's compliance posture stale for weeks.

Manual monitoring means someone periodically opens EUR-Lex, eyeballs a document, and decides whether anything changed. This approach has predictable failure modes:

- **Missed changes** — amendments to recitals or annexes go unnoticed because the reviewer skimmed Article headings.
- **Stale baselines** — nobody remembers what the document said last month, so there's nothing to diff against.
- **Unverifiable citations** — compliance memos quote regulation text that doesn't match the published source, either because it was paraphrased, truncated, or copied from an outdated consolidation.
- **No audit trail** — when a regulator asks "when did you become aware of this change?", the honest answer is "we're not sure."

### What CANARY Does

CANARY replaces manual monitoring with a deterministic, auditable pipeline:

1. **Fetch** — pull the current HTML text of each regulation from EUR-Lex.
2. **Detect** — compute a SHA-256 hash and compare it against the stored baseline. If the hash differs, generate a unified diff.
3. **Extract** — send the diff and source text to Claude for structured analysis: what changed, which articles are affected, how material is it, and what are the supporting quotes.
4. **Verify** — mechanically check every extracted citation against the source text. No substring match → flagged as unverified. No hallucinated quotes pass silently.
5. **Report** — generate a markdown change report with YAML frontmatter (regulation, severity, affected articles, run ID) ready for compliance triage.
6. **Store** — write the report to an Obsidian vault via Flywheel MCP, log to the daily note, and persist run metrics in SQLite.

### Manual Process vs CANARY

| Dimension | Manual monitoring | CANARY |
|-----------|-------------------|--------|
| **Check frequency** | Weekly / ad-hoc | Every run (schedulable) |
| **Time per check** | 30–60 min per regulation | ~15 seconds per source |
| **Change detection** | Human eyeball comparison | SHA-256 hash — deterministic, no false positives |
| **Coverage** | Whatever the reviewer remembers to check | Every configured CELEX ID, every run |
| **Citation accuracy** | Copy-paste, hope it's verbatim | Mechanically verified substring match with Unicode normalization |
| **Audit trail** | Email thread or spreadsheet | SQLite `run_log` + `source_check_log` + issue files, timestamped |
| **Cost per check** | Analyst time | ~$0.05 in API tokens per source (Sonnet) |
| **Deduplication** | Manual ("did we already flag this?") | Automatic via `canary_run_id` search |

### Guarantees and Trust Model

CANARY is designed around verifiability, not trust in AI output:

- **Every citation is mechanically verified.** Supporting quotes extracted by Claude are checked against the source text using normalized substring matching. If the quote isn't in the document, it's flagged as unverified — never silently accepted.
- **No hallucinated citations.** The verification pipeline uses 5 matching strategies (exact, quote-insensitive, prefix, quote-insensitive prefix, elision) with full Unicode normalization. Unverified quotes trigger an automatic re-quote attempt; if that also fails, the citation is marked unverified in the output.
- **Deterministic change detection.** SHA-256 hashing means identical documents always produce identical hashes. No probabilistic thresholds, no false positives.
- **Full audit trail.** Every run is recorded in SQLite (`run_log`, `source_check_log`) with timestamps, token counts, citation stats, and error details. Issue files are written to `data/issues/`.
- **Idempotent vault writes.** Before writing, CANARY searches the vault for the `canary_run_id`. If found, the write is skipped. The same run never writes twice.
- **Structured exit codes.** `0` = clean run, `1` = warnings (e.g. unverified citations), `2` = errors (e.g. fetch failure). CI-friendly.

### The Wider Lifecycle

CANARY fits into a compliance workflow like this:

```
First run            Stores baseline hash + full text for each source.
                     No extraction — there's nothing to diff against yet.
                              │
Scheduled monitoring          ▼
                     Runs periodically. Fetches each source, compares hashes.
                     If unchanged → logs "no change" and moves on.
                              │
Change detected               ▼
                     Generates diff, extracts structured changes via Claude,
                     verifies all citations, writes triage report to vault.
                              │
Compliance triage             ▼
                     A human reviews the report: severity, affected articles,
                     supporting quotes. Decides on action.
                              │
Objective extraction          ▼
                     `extract-objectives` pulls structured obligations from the
                     full regulation text: who must comply, what they must do,
                     legal basis, deadlines. Each objective becomes a vault note.
                              │
Obligation tracking           ▼
                     Objectives live in the vault as structured notes with
                     frontmatter (article, obligation_type, materiality, status).
                     Obsidian queries, dashboards, or downstream tools can
                     track compliance posture over time.
```

---

## Part 2 — Technical Deep Dive

### Architecture Overview

```
EUR-Lex ──→ fetch ──→ detect ──→ extract ──→ verify ──→ report ──→ vault
              │          │          │           │          │          │
           httpx     SHA-256    Claude     substring   markdown   Flywheel
           retry     difflib    Pydantic   matching    YAML FM      MCP
```

The pipeline is orchestrated by **LangGraph** as a state machine. Each node reads from and writes to a shared `CANARYState` TypedDict. A conditional edge after `detect_change` skips the LLM entirely when no change is detected.

```
┌──────────────┐
│ fetch_source │
└──────┬───────┘
       ▼
┌──────────────┐
│detect_change │
└──────┬───────┘
       ▼
  should_extract?
  ┌─────┴─────┐
  │ changed   │ unchanged
  ▼           ▼
┌──────────┐ ┌──────────────┐
│ extract  │ │output_results│
└────┬─────┘ └──────┬───────┘
     ▼              │
┌──────────┐        │
│ verify   │        │
└────┬─────┘        │
     ▼              │
┌──────────────┐    │
│output_results│    │
└──────┬───────┘    │
       ▼            ▼
┌────────────────────┐
│  write_to_vault    │
└────────────────────┘
         │
        END
```

### Pipeline Nodes

| Node | Input | What it does | Output | Error handling |
|------|-------|-------------|--------|----------------|
| `fetch_source` | `current_source` | Async HTTP fetch from EUR-Lex with ETag caching, 2s rate limiting, 5-attempt retry | `fetched_text`, `is_first_run` | Retries on timeout/connect errors; 429 respects `Retry-After` header |
| `detect_change` | `fetched_text` | SHA-256 hash comparison against stored baseline; unified diff if changed | `changed`, `old_hash`, `new_hash`, `diff_text` | First run stores baseline and returns `is_first_run: True` |
| `extract_obligations` | `diff_text`, `fetched_text` | Claude structured output → `ExtractionResult` with Pydantic enforcement | `extraction`, `extraction_metrics` | 3 attempts with exponential backoff (4–60s); warns if diff non-empty but 0 changes extracted |
| `verify_citations` | `extraction`, `fetched_text` | Mechanical substring match of every `supporting_quote` against source text | `verification` (VerificationReport) | Logs unverified count; never blocks pipeline |
| `output_results` | All prior state | Generates markdown report with YAML frontmatter, or JSON status for baseline/no-change | `report`, `tags` | Always succeeds |
| `write_to_vault` | `report`, `vault_enabled` | Dedup check → write report → log to daily note via Flywheel MCP | `vault_path` | Skips silently if `vault_enabled=False` or duplicate detected |

### LangGraph State

`CANARYState` (TypedDict, `total=False`):

| Field | Type | Set by |
|-------|------|--------|
| `sources` | `list[SourceConfig]` | Scheduler (input) |
| `current_source` | `SourceConfig` | Scheduler (input) |
| `run_id` | `str` | Scheduler (input) |
| `model` | `str` | Scheduler (input) |
| `fetched_text` | `str \| None` | `fetch_source` |
| `is_first_run` | `bool` | `detect_change` |
| `changed` | `bool` | `detect_change` |
| `old_hash` | `str \| None` | `detect_change` |
| `new_hash` | `str \| None` | `detect_change` |
| `diff_text` | `str \| None` | `detect_change` |
| `extraction` | `ExtractionResult \| None` | `extract_obligations` |
| `extraction_metrics` | `Any \| None` | `extract_obligations` |
| `verification` | `VerificationReport \| None` | `verify_citations` |
| `tags` | `dict \| None` | `output_results` |
| `report` | `str \| None` | `output_results` |
| `vault_path` | `str \| None` | `write_to_vault` |
| `vault_enabled` | `bool` | Scheduler (input) |
| `errors` | `list[str]` | Any node |

### Pydantic Data Models

All models in `src/canary/analysis/models.py`.

#### RegulatoryChange

Represents a single detected change in a regulation.

| Field | Type | Description |
|-------|------|-------------|
| `change_type` | `Literal["new_requirement", "amendment", "repeal", "guidance"]` | Nature of the change |
| `affected_articles` | `list[str]` | e.g. `["Article 8(1)", "Article 9"]` |
| `effective_date` | `str \| None` | When the change takes effect |
| `materiality` | `Literal["high", "medium", "low"]` | Impact assessment |
| `materiality_rationale` | `str` | One sentence with document evidence |
| `supporting_quotes` | `list[str]` | Verbatim from source, max 3 |
| `source_section` | `str` | Article/section reference |
| `confidence` | `float` | 0.0–1.0 |

#### ExtractionResult

Container for all changes detected in one source.

| Field | Type | Description |
|-------|------|-------------|
| `changes` | `list[RegulatoryChange]` | All detected changes |
| `source_celex_id` | `str` | CELEX ID of the source document |
| `summary` | `str` | Brief summary of all changes |

#### ComplianceObjective

A single regulatory obligation extracted from the full text.

| Field | Type | Description |
|-------|------|-------------|
| `article` | `str` | e.g. `"Article 4(1)(a)"` |
| `title` | `str` | Short title, max 10 words |
| `obligation_type` | `Literal["disclosure", "reporting", "governance", "process", "prohibition"]` | Category |
| `who` | `str` | e.g. `"financial market participants"` |
| `what` | `str` | Plain-language description, 1–3 sentences |
| `where` | `str` | e.g. `"on websites"`, `"in pre-contractual disclosures"` |
| `deadline` | `str \| None` | Compliance deadline if specified |
| `materiality` | `Literal["high", "medium", "low"]` | For EU asset managers operating Article 8/9 funds |
| `verbatim_quote` | `str` | Exact quote from regulation, max 300 chars |

#### ObjectiveExtraction

Container for all objectives from one extraction pass.

| Field | Type | Description |
|-------|------|-------------|
| `objectives` | `list[ComplianceObjective]` | All extracted objectives |
| `source_celex_id` | `str` | CELEX ID |
| `regulation_name` | `str` | Full name, e.g. `"Regulation (EU) 2019/2088 (SFDR)"` |
| `summary` | `str` | Scope and purpose |

### Citation Verification

Every quote extracted by Claude is mechanically verified against the source text. The verification pipeline in `src/canary/analysis/normalize.py` applies 5 strategies in order, stopping at the first match:

1. **Exact normalized match** — normalized quote is a substring of normalized source.
2. **Quote-insensitive match** — swap all quote characters (`"` ↔ `'`) and retry. Legal text varies between single and double quotes across consolidations.
3. **Prefix match** — if the quote is ≥80 characters, strip trailing `.` and check if the prefix exists. Handles Claude's tendency to truncate long quotes with `...`.
4. **Quote-insensitive prefix match** — combination of (2) and (3).
5. **Elision match** — split on `[...]` or `[…]`, verify each segment (≥40 chars) exists in the source in order. Handles quotes with internal omissions.

**Unicode normalization** (`normalize_for_matching`) applied before all matching:

| Transform | Examples |
|-----------|----------|
| NFKC normalization | NBSP (U+00A0) → space, fi ligature (U+FB01) → `fi` |
| Smart quotes → ASCII | `\u2018\u2019` → `'`, `\u201C\u201D` → `"`, guillemets → `"` |
| Dashes → hyphen | en-dash, em-dash, figure dash, minus sign → `-` |
| Invisible chars stripped | soft hyphen, zero-width space, ZWNJ, BOM, word joiner |
| Footnote markers stripped | `*1`, `*14` etc. (EUR-Lex proposal inline markers) |
| Whitespace collapsed | runs of whitespace → single space |
| Lowercased | case-insensitive comparison |

### Chunked Extraction

Documents exceeding 680,000 characters (~170K tokens) are split into overlapping chunks for extraction.

**Context budget calculation:**

| Constant | Value | Rationale |
|----------|-------|-----------|
| `_MODEL_CONTEXT_TOKENS` | 200,000 | Sonnet/Opus/Haiku context window |
| `_RESERVED_TOKENS` | 30,000 | System prompt + user template + output + safety margin |
| `_CHARS_PER_TOKEN` | 4 | Conservative estimate |
| `_MAX_SOURCE_CHARS` | 680,000 | (200K − 30K) × 4 |
| `_CHUNK_OVERLAP_CHARS` | 8,000 | Captures articles straddling chunk boundaries |

**Splitting strategy** (`_split_chunks`):

- If the text fits in one chunk, no splitting occurs.
- Otherwise, look for a paragraph break (`\n\n`) within a 2,000-char look-ahead zone near the chunk boundary. Fall back to a line break (`\n`) if no paragraph break is found.
- Each subsequent chunk starts `overlap` characters before the previous chunk ended.
- Guarantees forward progress: `end = max(end, start + 1)`.

**Merge and dedup:**

- Each chunk is sent to Claude independently.
- Results are merged, **deduplicated by article reference** (first occurrence wins).
- Metrics are aggregated: summed tokens, summed duration, chunk count recorded.

### Re-Quote Pipeline

When citation verification fails, CANARY automatically attempts to repair the quote.

`requote_citations()` in `src/canary/analysis/objectives.py`:

1. Collect all objectives with unverified `verbatim_quote` fields.
2. Format them into a prompt listing the article, title, obligation type, who, what, and the first 200 chars of the original quote.
3. Send the full source text + formatted list to Claude with instructions to find the **exact passage** that establishes each obligation.
4. Claude returns a `RequoteResult` with corrected objectives.
5. For each corrected quote, re-run citation verification. If it now passes, replace the original.
6. Log: `"Re-quoted N/M citations (XXms, I/O tokens)"`.

Retry: 2 attempts, exponential backoff (4–60s). Output tokens: `min(max(len(objectives) * 400 + 2000, 4096), 16384)`.

### EUR-Lex Fetcher

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

### SQLite Storage

`src/canary/detection/store.py` — `DocumentStore` at `data/canary.db`

**Schema version:** 2 (stored in `schema_version` table, migration on open).

#### Tables

**`document_state`** — current baseline per source

| Column | Type | Description |
|--------|------|-------------|
| `celex_id` | TEXT PK | EUR-Lex CELEX identifier |
| `hash` | TEXT NOT NULL | SHA-256 of current text |
| `text` | TEXT NOT NULL | Full document text |
| `last_checked` | TEXT NOT NULL | ISO timestamp |
| `last_changed` | TEXT | ISO timestamp, nullable |

**`change_log`** — every detected change (audit trail)

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTO | Row ID |
| `celex_id` | TEXT NOT NULL | Source identifier |
| `detected_at` | TEXT NOT NULL | ISO timestamp |
| `old_hash` | TEXT | Previous hash (null on first change) |
| `new_hash` | TEXT NOT NULL | New SHA-256 hash |
| `diff_summary` | TEXT | First 200 lines of unified diff |
| `materiality` | TEXT | low/medium/high |
| `canary_run_id` | TEXT | Groups changes by pipeline run |

**`run_log`** — per pipeline execution

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | e.g. `run-3e58d4b8c79e` |
| `started_at` | TEXT NOT NULL | ISO timestamp |
| `completed_at` | TEXT | ISO timestamp |
| `duration_ms` | REAL | Wall-clock duration |
| `sources_checked` | INTEGER | Number of sources processed |
| `changes_detected` | INTEGER | Sources with hash changes |
| `baselines_stored` | INTEGER | First-run baseline stores |
| `errors` | INTEGER | Error count |
| `extraction_tokens_in` | INTEGER | Total input tokens to Claude |
| `extraction_tokens_out` | INTEGER | Total output tokens |
| `summary_json` | TEXT | Full run summary as JSON |

**`source_check_log`** — per-source per-run detail

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTO | Row ID |
| `run_id` | TEXT NOT NULL | FK → `run_log.run_id` |
| `celex_id` | TEXT NOT NULL | Source identifier |
| `label` | TEXT NOT NULL | Human-readable source name |
| `status` | TEXT NOT NULL | `pending` / `baseline` / `no_change` / `changed` / `error` |
| `started_at` | TEXT | ISO timestamp |
| `duration_ms` | REAL | Per-source duration |
| `hash` | TEXT | SHA-256 |
| `change_count` | INTEGER | Changes extracted |
| `citations_total` | INTEGER | Total quotes to verify |
| `citations_verified` | INTEGER | Quotes that passed verification |
| `vault_path` | TEXT | Path written to vault |
| `error` | TEXT | Error message if status=error |

**Indexes:** `idx_change_log_celex`, `idx_source_check_run`, `idx_run_log_started`.

**Pruning:** `prune(days=90)` deletes run_log and source_check_log entries older than N days, then `VACUUM`.

### Vault Integration

`src/canary/output/vault.py` — `VaultWriter`

Connects to the Flywheel MCP server via `langchain-mcp-adapters` `MultiServerMCPClient` (stdio transport).

**Configuration:**

| Setting | Default | Env override |
|---------|---------|--------------|
| MCP server path | `~/src/flywheel-memory/packages/mcp-server/dist/index.js` | `CANARY_MCP_SERVER` |
| Vault path | `~/obsidian/Canary` | `FLYWHEEL_VAULT` |
| Writer preset | `writer` | — |

**MCP tools used:**

| Tool | Purpose |
|------|---------|
| `search` | Deduplication — search for `canary_run_id` before writing |
| `vault_create_note` | Write change reports and objective notes |
| `vault_add_to_section` | Append timestamped entries to daily note "Log" section |

**Write paths:**

- Change reports: `work/compliance/reports/{date}-{source_id}.md`
- Objectives: `work/compliance/objectives/{regulation_short}/{article-ref}.md` (article sanitized: `Article 4(1)(a)` → `article-4-1-a`)
- Daily log: `daily-notes/{date}.md` → "Log" section, `timestamp-bullet` format

**Deduplication:** Before every write, `check_duplicate(run_id)` searches the vault for the `canary_run_id`. If a match is found, the write is skipped entirely.

### Observability

**LangSmith tracing** (`src/canary/tracing.py`):

If `LANGSMITH_API_KEY` (or `LANGCHAIN_API_KEY`) is set, CANARY enables LangSmith tracing:
- Project: `canary`
- Run ID: passed through as `LANGCHAIN_RUN_ID`
- All LangGraph node executions and Claude calls are traced.

**RunMetrics:**

Tracked per run: `run_id`, `started_at`, `completed_at`, `duration_ms`, `sources_checked`, `changes_detected`, `baselines_stored`, `errors`, `extraction_tokens_in`, `extraction_tokens_out`, plus a list of `SourceCheckMetrics`.

Cost estimation in `summary()`: input tokens × $3/M + output tokens × $15/M (Sonnet pricing).

**IssueCollector** (`src/canary/issues.py`):

Structured issue tracking per pipeline run. Each issue has: `severity` (error/warning), `stage` (fetch/detect/extract/verify/vault/objective), `source`, `message`, `detail`, `timestamp`. Issues are written to `data/issues/{run_id}.json`. Error/warning counts drive the exit code.

**Status command:**

`canary status` shows the 5 most recent runs, source-by-source detail for the latest run, and the last 5 issue files.

---

## Part 3 — Operations

### Quick Start

```bash
# Clone and install
git clone git@github.com:velvetmonkey/canary.git
cd canary
uv sync

# Configure
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY

# Run change detection (writes to vault by default)
uv run canary

# Extract compliance objectives from SFDR
uv run canary extract-objectives --source SFDR-L1 --count 10

# Console-only mode (no vault writes)
uv run canary --no-vault
```

### Commands

#### Change detection (default)

```bash
uv run canary                          # Monitor all sources, write to vault
uv run canary --no-vault               # Console output only
uv run canary --source SFDR-L1         # Single source
uv run canary --model claude-sonnet-4-6  # Override model
```

Fetches each configured source, compares against stored baseline, and if changed:
- Computes a unified diff
- Sends diff + source text to Claude for structured extraction
- Mechanically verifies all citations
- Generates a markdown report with YAML frontmatter
- Writes to Obsidian vault and logs to daily note

On first run, stores the baseline hash and text — no extraction needed.

#### Objective extraction

```bash
uv run canary extract-objectives                          # All objectives from first source
uv run canary extract-objectives --source SFDR-L1         # Specific source
uv run canary extract-objectives --count 20               # 20 most important objectives
uv run canary extract-objectives --no-vault               # Console only
```

Extracts structured compliance objectives from the full regulation text:
- Who must comply, what they must do, where/how, deadlines
- Verbatim legal basis quote with mechanical verification
- Automatic re-quote for unverified citations
- Writes each objective as an individual vault note + regulation index README

#### Status

```bash
uv run canary status
```

Shows recent run history: last 5 runs with status icons, source-by-source detail for the latest run, and recent issue files.

#### Prune

```bash
uv run canary prune              # Delete runs older than 90 days
uv run canary prune --days 30    # Custom retention period
```

Removes old `run_log` and `source_check_log` entries, then `VACUUM`s the database.

### Configuration

#### Environment (`.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `CANARY_DB_PATH` | No | `data/canary.db` | SQLite database path |
| `CANARY_MCP_SERVER` | No | `~/src/flywheel-memory/.../index.js` | Flywheel MCP server path |
| `FLYWHEEL_VAULT` | No | `~/obsidian/Canary` | Obsidian vault path |
| `CANARY_MODEL` | No | `claude-sonnet-4-6` | Default model for extraction |
| `CANARY_CONFIG` | No | `config/sources.yaml` | Source configuration file |
| `LANGSMITH_API_KEY` | No | — | Enables LangSmith tracing |

#### Global CLI options

| Flag | Description |
|------|-------------|
| `--no-vault` | Disable vault writes (console output only) |
| `--source ID` | Filter to a single source by ID |
| `--model MODEL` | Override extraction model |
| `--config PATH` | Override source config file |
| `-v` / `--verbose` | DEBUG log level |
| `-q` / `--quiet` | WARNING log level |

#### Sources (`config/sources.yaml`)

```yaml
sources:
  - id: SFDR-L1
    celex_id: "32019R2088"
    label: "SFDR Level 1 — Reg (EU) 2019/2088"
    fetcher: eurlex
    priority: critical
```

Each source needs:
- `id` — short identifier used in filenames and CLI flags
- `celex_id` — EUR-Lex CELEX number
- `label` — human-readable name
- `fetcher` — fetcher type (`eurlex` for Phase 1)
- `priority` — `critical` or `high`

### Vault Output Structure

```
~/obsidian/Canary/
├── work/compliance/
│   ├── reports/                        # Change detection reports
│   │   └── 2026-03-11-SFDR-L1.md
│   └── objectives/                     # Compliance objectives
│       └── sfdr-l1/
│           ├── article-3-1.md
│           ├── article-4-1.md
│           └── ...
└── daily-notes/
    └── 2026-03-11.md                   # Daily log entries
```

> **See [`output/`](output/) for real extraction output** — 453 compliance objectives across 14 regulations in 5 jurisdictions, each with verified citations and cross-linked wikilinks. This is actual CANARY output, not synthetic examples.

### Output Formats

#### Change report (YAML frontmatter)

```yaml
---
type: regulatory-change
regulation: SFDR
jurisdiction: EU
severity: high
status: unreviewed
detected: 2026-03-11
source_url: https://eur-lex.europa.eu/...
affects:
  - Article 8(1)
canary_run_id: run-3e58d4b8c79e
---
```

#### Compliance objective (YAML frontmatter)

```yaml
---
type: compliance-objective
regulation: Regulation (EU) 2019/2088 (SFDR)
celex_id: 32019R2088
article: "Article 8(1)"
obligation_type: disclosure
materiality: high
status: active
extracted: 2026-03-11
citation: verified
source_url: https://eur-lex.europa.eu/...
canary_run_id: obj-9e70ff63fb9f
---
```

#### Run summary (JSON)

```json
{
  "run_id": "run-3e58d4b8c79e",
  "duration_ms": 16197,
  "sources_checked": 3,
  "changes_detected": 1,
  "extraction_tokens": { "input": 13053, "output": 715 },
  "sources": [
    {
      "celex_id": "32019R2088",
      "status": "changed",
      "change_count": 2,
      "citations": "2/4"
    }
  ]
}
```

### Testing

```bash
uv run pytest                                    # All 91 unit tests
uv run pytest -m "not integration and not llm"   # Fast tests only (no network, no LLM)
uv run pytest tests/unit/test_graph_e2e.py       # End-to-end graph tests
uv run ruff check src/ tests/                    # Lint
```

**Test markers:**

| Marker | Description |
|--------|-------------|
| `integration` | Hits live external services (EUR-Lex). Requires network. |
| `llm` | Requires a live Claude API call. Requires `ANTHROPIC_API_KEY`. |

91 unit tests covering:
- EUR-Lex HTML extraction and text cleanup
- SHA-256 hashing, difflib diffs, SQLite CRUD
- Pydantic model validation, citation verification (all 5 strategies)
- Unicode normalization (smart quotes, dashes, ligatures, invisible chars, footnote markers)
- Chunked extraction with overlapping dedup
- LangGraph compilation and conditional edges
- Full pipeline E2E (first run, no change, change, unverified citations, fetch errors)
- Mocked Claude extraction with token tracking
- Vault writer with mocked MCP tools
- Re-quote pipeline
- Run metrics and LangSmith configuration
- Issue collection and status command

### Dependencies

| Package | Purpose | Why this choice | Outcome |
|---------|---------|-----------------|---------|
| `httpx` | Async HTTP client for EUR-Lex | Native async/await, HTTP/2, connection pooling. `requests` can't do concurrent fetches without threads. | Fetches 14 sources concurrently with ETag caching and proper rate limiting — each check completes in ~15s total. |
| `tenacity` | Retry with exponential backoff | Declarative retry policies (decorators + composable strategies). Cleaner than hand-rolled retry loops. | EUR-Lex 429s and transient timeouts are handled automatically with configurable backoff (4–60s), keeping the pipeline resilient without manual intervention. |
| `beautifulsoup4` + `lxml` | HTML parsing and text extraction | `lxml` is the fastest Python HTML parser. BeautifulSoup provides a tolerant API on top — important because EUR-Lex HTML is inconsistent across document types. | Reliable text extraction from messy legal HTML: strips navigation chrome, removes inline footnote markers that break citation matching, preserves whitespace structure. |
| `anthropic` | Claude API client | Direct API access for token counting and cost tracking. | Precise per-run cost reporting ($0.05/source typical) and structured token metrics in the audit trail. |
| `langchain-anthropic` | Claude structured output bridge | Pydantic-enforced structured output via `with_structured_output()`. Handles JSON schema generation, retries on malformed responses, and type coercion automatically. | Claude's extraction output is guaranteed to conform to the `RegulatoryChange` / `ComplianceObjective` schemas — no parsing failures, no missing fields. |
| `langgraph` | Pipeline orchestration (state machine) | Explicit state machine with conditional edges. Each node is independently testable. The graph skips the LLM entirely when no change is detected. | Deterministic pipeline flow: fetch → detect → (skip if unchanged) → extract → verify → report → vault. Easy to add new nodes without refactoring. |
| `langgraph-checkpoint-sqlite` | State persistence | Built-in checkpointing for LangGraph — resumes from last successful node on failure. | A crash mid-pipeline doesn't lose earlier work. Re-running picks up where it left off. |
| `pydantic` | Schema enforcement for extraction models | Runtime type validation with clear error messages. Claude's structured output mode uses the Pydantic schema directly. | Every extracted change and objective is validated at the boundary — malformed LLM output is caught immediately, not downstream. |
| `langchain-mcp-adapters` + `mcp` | Vault writes via Flywheel MCP | MCP (Model Context Protocol) provides a standard interface to the Obsidian vault through Flywheel. Writes are idempotent and deduplicated. | Change reports and compliance objectives land directly in Obsidian as structured, queryable notes — no manual import step. |
| `python-dotenv` | Environment configuration | Standard `.env` file loading. | Single configuration point for API keys, paths, and model selection — no hardcoded secrets. |
| `pyyaml` | Source config parsing | YAML is more readable than JSON for configuration with comments. | `sources.yaml` is human-editable: adding a new jurisdiction or regulation is a 5-line config change. |

Dev: `pytest`, `pytest-asyncio`, `pytest-httpx`, `ruff`.

#### Design Philosophy

The technology choices follow three principles:

1. **Verify, don't trust.** The LLM extracts structured data, but every citation is mechanically verified against source text. SHA-256 hashing provides deterministic change detection with zero false positives. Pydantic enforces schemas at every boundary. The system is designed so that AI failures are caught, not propagated.

2. **Audit everything.** SQLite logs every run, every source check, every citation result with timestamps and token counts. Structured exit codes (0/1/2) make CI integration straightforward. Issue files provide forensic detail when something goes wrong. A regulator asking "when did you know?" gets a precise, timestamped answer.

3. **Skip work that doesn't need doing.** The LangGraph conditional edge skips Claude entirely when a document hasn't changed. ETag caching avoids re-downloading unchanged content. Vault deduplication prevents duplicate writes. The result is ~$0.05 and ~15 seconds per source — cheap enough to run on every commit or every hour.

### Currently Monitored Sources

See [`config/sources.yaml`](config/sources.yaml) for the full list. 14 sources across 5 jurisdictions:

**EU** (via EUR-Lex): SFDR L1, SFDR RTS, SFDR 2.0 Proposal, EU Taxonomy, MiFID II Sustainability

**UK** (via legislation.gov.uk): Financial Services Act 2023, TCFD Regulations 2022, SDR Regulations 2023, Climate Change Act 2008, Environment Act 2021, ESOS Regulations 2022

**US** (via GovInfo): Sarbanes-Oxley Act 2002

**NZ** (via legislation.govt.nz): Financial Markets Conduct Act 2013

**IE** (via Irish Statute Book): Companies Act 2014

### Roadmap / Phase 2

- **Compliance matrix RAG** — cross-reference extracted objectives against firm policies to identify gaps.
- **More sources** — SEC rules (when API available), FCA Handbook, BaFin, ESMA Q&A.
- **Scheduling / cron** — automated periodic runs via systemd timer or cron.
- **Alerting** — Slack/email notifications on change detection or unverified citations.
- **Obligation tracking dashboard** — Obsidian queries or dedicated UI for compliance posture over time.

---

## Independent Code Review (Grok)

*The following review was produced by Grok after examining the public repository, codebase, and documentation.*

### Product Assessment

CANARY is a focused, high-quality RegTech tool that solves a real pain point extremely well. It's **not** just another LLM wrapper — the verification layer and deterministic change detection make it trustworthy for compliance use. It's also part of a larger Obsidian + MCP ecosystem (Flywheel for querying, Crank for mutations), turning a vault into a live compliance knowledge graph.

**Strengths:**

- **Auditability and trust model is class-leading.** Every citation is verified with 5 matching strategies plus heavy Unicode normalization (NFKC, smart quotes → ASCII, dashes → hyphens, footnote stripping, whitespace collapse). Re-quote repair loop fixes edge cases. Full SQLite trail (`run_log`, `change_log`, `source_check_log`, `canary_run_id` deduping). Structured exit codes (0 = clean, 1 = warnings, 2 = errors).
- **Efficiency.** ~15 seconds per source, ~$0.05 API cost, early-exit in LangGraph if no change.
- **Smart integration.** Drops directly into Obsidian as triage-ready notes and obligations you can query. Idempotent writes, automatic daily logging.
- **Niche perfection.** Exactly what ESG/compliance teams in finance need. Manual monitoring is painful and error-prone; this replaces it with something defensible.
- **Modern and polished.** CLI (`canary status`, `prune`, etc.), 91 tests, clean docs, roadmapped features (RAG compliance matrix, more jurisdictions, scheduling).

**Opportunities:**

- Claude-only (easy to fix with LLM abstraction layer).
- EUR-Lex only for now (sources.yaml makes expansion straightforward).
- No built-in scheduler/alerting yet (roadmap item; easy to add cron/Docker + Slack).
- Obsidian/Flywheel dependency (great if you're in that ecosystem; optional plain JSON/Markdown export would broaden appeal).

**Market fit:** Strong for EU sustainable finance teams, asset managers, consultants. No direct competitor combines hash-based change detection + mechanical verification + Obsidian MCP output this cleanly.

### Code Assessment

Modern Python stack (uv + pyproject.toml + uv.lock, Python version pinned, ruff linting). Structure is clean: `src/canary/` core modules, `tests/` with 91 tests, `config/` for sources.yaml.

**Architecture** — LangGraph state machine with clear, single-responsibility nodes: `fetch_source`, `detect_change`, `extract_obligations`, `verify_citations`, `output_results`, `write_to_vault`. Pydantic models (`RegulatoryChange`, `ExtractionResult`, `ComplianceObjective`, etc.) for strict validation. Conditional edge after `detect_change` skips the LLM entirely when no change is detected — significant cost saver.

**Code quality highlights:**

- **fetchers/eurlex.py** — async httpx, ETag caching, tenacity retries (exp backoff 4–60s), careful BeautifulSoup stripping (nav/header/footer + footnote tags), whitespace-preserving `get_text()`, proper rate limiting. Handles 429s gracefully. Production-grade.
- **Verification/normalize logic** — the standout module. 5 strategies (exact, quote-insensitive, prefix ≥80 chars, elision handling), heavy normalization, footnote cleanup. This is exactly how legal-tech AI should be built.
- **Overall engineering maturity** — async where it matters, checkpointing with langgraph-checkpoint-sqlite, MCP adapters for Obsidian, idempotent writes, pruning/VACUUM on SQLite, structured logging. Testing, modularity, error handling, and observability (LangSmith compatible) are all strong.

**Suggestions:**

- Abstract the LLM layer (easy win for OpenAI/Gemini/self-hosted fallback + cost tracking).
- Add explicit per-run token/cost metrics (already partially there via run_log).
- Regression tests with historical regulation snapshots would be perfect for the verification engine.
- The verification/normalizer module would be valuable as a standalone reusable library for the legal AI community.

**Verdict:** Clean, robust, thoughtful, and clearly written by someone who understands both the domain and modern Python tooling. Already more polished than most production tools.

---

## License

Copyright (c) 2026 Ben Campbell. All rights reserved. See [LICENSE](LICENSE).
