# CANARY

ESG regulatory change monitoring agent. Python 3.12 + uv.

## Architecture

LangGraph pipeline: fetch → detect → extract → verify → output → vault

| Directory | Purpose |
|-----------|---------|
| `src/canary/fetchers/` | Source fetchers (EUR-Lex for Phase 1) |
| `src/canary/detection/` | SHA-256 hashing, difflib diffs, SQLite store |
| `src/canary/analysis/` | Pydantic models, Claude extraction, citation verification |
| `src/canary/graph/` | LangGraph state, nodes, graph assembly |
| `src/canary/output/` | Report generation, vault writer, alerts (stub) |
| `config/sources.yaml` | Watched CELEX IDs |
| `data/canary.db` | SQLite state (gitignored) |

## Commands

```bash
uv run python -m canary.scheduler              # Run pipeline (console output)
uv run python -m canary.scheduler --vault       # Run + write reports to Obsidian vault
uv run pytest -m "not integration and not llm"  # Unit tests
uv run ruff check src/ tests/                   # Lint
```

## Key Patterns

- Module-level singletons for store/fetcher/vault_writer (set via `set_store()`/`set_fetcher()`/`set_vault_writer()`)
- All fetcher methods are async
- Citation verification is mechanical (normalized whitespace + case-insensitive substring match)
- First run stores baseline hash — no extraction on first run
- Graph skips LLM extraction when no change detected (conditional edge)
- Vault writer uses `langchain-mcp-adapters` MultiServerMCPClient → flywheel-memory stdio
- `--vault` flag enables vault write; without it, reports go to console only
- Vault deduplication via `canary_run_id` search before writing
