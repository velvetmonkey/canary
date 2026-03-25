# Storage and Audit Trail

[< Back to README](../README.md)

## SQLite Storage

`src/canary/detection/store.py` — `DocumentStore` at `data/canary.db`

**Schema version:** 2 (stored in `schema_version` table, migration on open).

### Tables

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

## Observability

### LangSmith Tracing

`src/canary/tracing.py`:

If `LANGSMITH_API_KEY` (or `LANGCHAIN_API_KEY`) is set, CANARY enables LangSmith tracing:
- Project: `canary`
- Run ID: passed through as `LANGCHAIN_RUN_ID`
- All LangGraph node executions and Claude calls are traced.

### RunMetrics

Tracked per run: `run_id`, `started_at`, `completed_at`, `duration_ms`, `sources_checked`, `changes_detected`, `baselines_stored`, `errors`, `extraction_tokens_in`, `extraction_tokens_out`, plus a list of `SourceCheckMetrics`.

Cost estimation in `summary()`: input tokens × $3/M + output tokens × $15/M (Sonnet pricing).

### IssueCollector

`src/canary/issues.py`:

Structured issue tracking per pipeline run. Each issue has: `severity` (error/warning), `stage` (fetch/detect/extract/verify/vault/objective), `source`, `message`, `detail`, `timestamp`. Issues are written to `data/issues/{run_id}.json`. Error/warning counts drive the exit code.

### Status Command

`canary status` shows the 5 most recent runs, source-by-source detail for the latest run, and the last 5 issue files.
