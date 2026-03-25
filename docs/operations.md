# Operations

[< Back to README](../README.md)

## Quick Start

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

## Commands

### Change detection (default)

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

### Objective extraction

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

### Status

```bash
uv run canary status
```

Shows recent run history: last 5 runs with status icons, source-by-source detail for the latest run, and recent issue files.

### Prune

```bash
uv run canary prune              # Delete runs older than 90 days
uv run canary prune --days 30    # Custom retention period
```

Removes old `run_log` and `source_check_log` entries, then `VACUUM`s the database.

## Configuration

### Environment (`.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `CANARY_DB_PATH` | No | `data/canary.db` | SQLite database path |
| `CANARY_MCP_SERVER` | No | `~/src/flywheel-memory/.../index.js` | Flywheel MCP server path |
| `FLYWHEEL_VAULT` | No | `~/obsidian/Canary` | Obsidian vault path |
| `CANARY_MODEL` | No | `claude-sonnet-4-6` | Default model for extraction |
| `CANARY_CONFIG` | No | `config/sources.yaml` | Source configuration file |
| `LANGSMITH_API_KEY` | No | — | Enables LangSmith tracing |

### Global CLI options

| Flag | Description |
|------|-------------|
| `--no-vault` | Disable vault writes (console output only) |
| `--source ID` | Filter to a single source by ID |
| `--model MODEL` | Override extraction model |
| `--config PATH` | Override source config file |
| `-v` / `--verbose` | DEBUG log level |
| `-q` / `--quiet` | WARNING log level |

### Sources (`config/sources.yaml`)

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
- `fetcher` — fetcher type (`eurlex`, `ukleg`, `govinfo`, `nzleg`, `irishstatute`)
- `priority` — `critical` or `high`

## Currently Monitored Sources

See [`config/sources.yaml`](../config/sources.yaml) for the full list. 14 sources across 5 jurisdictions:

**EU** (via EUR-Lex): SFDR L1, SFDR RTS, SFDR 2.0 Proposal, EU Taxonomy, MiFID II Sustainability

**UK** (via legislation.gov.uk): Financial Services Act 2023, TCFD Regulations 2022, SDR Regulations 2023, Climate Change Act 2008, Environment Act 2021, ESOS Regulations 2022

**US** (via GovInfo): Sarbanes-Oxley Act 2002

**NZ** (via legislation.govt.nz): Financial Markets Conduct Act 2013

**IE** (via Irish Statute Book): Companies Act 2014

## Testing

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
