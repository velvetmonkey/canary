# Architecture

[< Back to README](../README.md)

## Architecture Overview

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

## Pipeline Nodes

| Node | Input | What it does | Output | Error handling |
|------|-------|-------------|--------|----------------|
| `fetch_source` | `current_source` | Async HTTP fetch from EUR-Lex with ETag caching, 2s rate limiting, 5-attempt retry | `fetched_text`, `is_first_run` | Retries on timeout/connect errors; 429 respects `Retry-After` header |
| `detect_change` | `fetched_text` | SHA-256 hash comparison against stored baseline; unified diff if changed | `changed`, `old_hash`, `new_hash`, `diff_text` | First run stores baseline and returns `is_first_run: True` |
| `extract_obligations` | `diff_text`, `fetched_text` | Claude structured output → `ExtractionResult` with Pydantic enforcement | `extraction`, `extraction_metrics` | 3 attempts with exponential backoff (4–60s); warns if diff non-empty but 0 changes extracted |
| `verify_citations` | `extraction`, `fetched_text` | Mechanical substring match of every `supporting_quote` against source text | `verification` (VerificationReport) | Logs unverified count; never blocks pipeline |
| `output_results` | All prior state | Generates markdown report with YAML frontmatter, or JSON status for baseline/no-change | `report`, `tags` | Always succeeds |
| `write_to_vault` | `report`, `vault_enabled` | Dedup check → write report → log to daily note via Flywheel MCP | `vault_path` | Skips silently if `vault_enabled=False` or duplicate detected |

## LangGraph State

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

## Pydantic Data Models

All models in `src/canary/analysis/models.py`.

### RegulatoryChange

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

### ExtractionResult

Container for all changes detected in one source.

| Field | Type | Description |
|-------|------|-------------|
| `changes` | `list[RegulatoryChange]` | All detected changes |
| `source_celex_id` | `str` | CELEX ID of the source document |
| `summary` | `str` | Brief summary of all changes |

### ComplianceObjective

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

### ObjectiveExtraction

Container for all objectives from one extraction pass.

| Field | Type | Description |
|-------|------|-------------|
| `objectives` | `list[ComplianceObjective]` | All extracted objectives |
| `source_celex_id` | `str` | CELEX ID |
| `regulation_name` | `str` | Full name, e.g. `"Regulation (EU) 2019/2088 (SFDR)"` |
| `summary` | `str` | Scope and purpose |
