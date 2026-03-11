# CANARY

**C**ompliance **AN**alysis and **A**utomated **R**egulatory **Y**ield — an ESG regulatory change monitoring agent.

CANARY watches EU regulatory sources (EUR-Lex), detects document changes via content hashing, extracts structured compliance data using Claude, mechanically verifies all citations, and writes reports to an Obsidian vault.

## What it does

1. **Fetches** regulatory documents from EUR-Lex (SFDR Level 1, RTS, proposals)
2. **Detects changes** by comparing SHA-256 hashes against a stored baseline
3. **Extracts** structured regulatory changes via Claude with Pydantic schema enforcement
4. **Verifies** every citation mechanically against the source text
5. **Writes** change reports and compliance objectives to an Obsidian vault via [Flywheel](https://github.com/velvetmonkey/flywheel-memory) MCP

## Quick start

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
uv run canary                   # Monitor all sources, write to vault
uv run canary --no-vault        # Console output only
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
uv run canary extract-objectives                          # 10 objectives from first source
uv run canary extract-objectives --source SFDR-L1         # Specific source
uv run canary extract-objectives --count 20               # More objectives
uv run canary extract-objectives --no-vault               # Console only
```

Extracts structured compliance objectives from the full regulation text:
- Who must comply, what they must do, where/how, deadlines
- Verbatim legal basis quote with mechanical verification
- Writes each objective as an individual vault note

## Configuration

### Environment (`.env`)

```bash
ANTHROPIC_API_KEY=sk-ant-...           # Required — Claude API key
CANARY_DB_PATH=data/canary.db          # Optional — SQLite path (default: data/canary.db)
CANARY_MCP_SERVER=~/src/flywheel-...   # Optional — MCP server path
FLYWHEEL_VAULT=~/obsidian/Canary       # Optional — vault path (default: ~/obsidian/Canary)
LANGSMITH_API_KEY=lsv2_...             # Optional — enables LangSmith tracing
```

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
- `fetcher` — fetcher type (`eurlex` for Phase 1)
- `priority` — `critical` or `high`

### Vault output structure

```
~/obsidian/Canary/
├── work/compliance/
│   ├── reports/                        # Change detection reports
│   │   └── 2026-03-11-SFDR-L1.md
│   └── objectives/                     # Compliance objectives
│       └── sfdr-l1/
│           ├── article-3-1.md
│           ├── article-4-1.md
│           ├── article-5-1.md
│           ├── article-6-1.md
│           ├── article-7-1.md
│           ├── article-8-1.md
│           ├── article-9-1-2-3.md
│           ├── article-10-1.md
│           ├── article-11-1.md
│           └── article-13-1.md
└── daily-notes/
    └── 2026-03-11.md                   # Daily log entries
```

## Output formats

### Change report (YAML frontmatter)

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

### Compliance objective (YAML frontmatter)

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

### Run summary (JSON)

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

## Architecture

```
EUR-Lex ──→ fetch ──→ detect ──→ extract ──→ verify ──→ report ──→ vault
              │          │          │           │          │          │
           httpx     SHA-256    Claude     substring   markdown   Flywheel
           retry     difflib    Pydantic   matching    YAML FM      MCP
```

### Pipeline (LangGraph)

| Node | What it does |
|------|-------------|
| `fetch_source` | Async HTTP fetch from EUR-Lex with retry + ETag caching |
| `detect_change` | SHA-256 hash comparison, unified diff if changed |
| `extract_obligations` | Claude structured output → `ExtractionResult` (skipped if no change) |
| `verify_citations` | Mechanical substring match of every quote against source text |
| `output_results` | Console JSON + markdown report generation |
| `write_to_vault` | Flywheel MCP → Obsidian vault (with deduplication) |

### Storage (SQLite)

| Table | Purpose |
|-------|---------|
| `document_state` | Latest text + SHA-256 hash per CELEX ID |
| `change_log` | Every detected change with diff summary |
| `run_log` | Per-run metrics (timing, tokens, errors) |
| `source_check_log` | Per-source-per-run detail |

## Testing

```bash
uv run pytest                                    # All 91 unit tests
uv run pytest -m "not integration and not llm"   # Fast tests only
uv run pytest tests/unit/test_graph_e2e.py       # End-to-end graph tests
uv run ruff check src/ tests/                    # Lint
```

91 unit tests covering:
- EUR-Lex HTML extraction and text cleanup
- SHA-256 hashing, difflib diffs, SQLite CRUD
- Pydantic model validation, citation verification
- LangGraph compilation and conditional edges
- Full pipeline E2E (first run, no change, change, unverified citations, fetch errors)
- Mocked Claude extraction with token tracking
- Vault writer with mocked MCP tools
- Run metrics and LangSmith configuration

## Dependencies

| Package | Purpose |
|---------|---------|
| `httpx` | Async HTTP client for EUR-Lex |
| `tenacity` | Retry with exponential backoff |
| `beautifulsoup4` + `lxml` | HTML parsing and text extraction |
| `langchain-anthropic` | Claude structured output |
| `langgraph` | Pipeline orchestration |
| `pydantic` | Schema enforcement |
| `langchain-mcp-adapters` + `mcp` | Vault writes via Flywheel MCP |
| `python-dotenv` | Environment configuration |
| `pyyaml` | Source config |

## License

Private — [velvetmonkey/canary](https://github.com/velvetmonkey/canary)
