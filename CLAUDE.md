# CANARY

ESG regulatory change monitoring agent. Python 3.12 + uv.

## Architecture

LangGraph pipeline: fetch → detect → extract → verify → output → vault

| Directory | Purpose |
|-----------|---------|
| `src/canary/fetchers/` | Source fetchers (EUR-Lex for Phase 1) |
| `src/canary/detection/` | SHA-256 hashing, difflib diffs, SQLite store |
| `src/canary/analysis/` | Pydantic models, Claude extraction, citation verification, objective extraction |
| `src/canary/graph/` | LangGraph state, nodes, graph assembly |
| `src/canary/output/` | Report generation, vault writer, alerts (stub) |
| `config/sources.yaml` | Watched CELEX IDs |
| `data/canary.db` | SQLite state (gitignored) |

## Commands

```bash
uv run canary                                             # Change detection (vault writes on by default)
uv run canary --no-vault                                  # Console output only
uv run canary extract-objectives --source SFDR-L1         # Extract compliance objectives
uv run canary extract-objectives --count 20 --no-vault    # More objectives, console only
uv run pytest                                             # 91 unit tests
uv run ruff check src/ tests/                             # Lint
```

## Key Patterns

- Module-level singletons for store/fetcher/vault_writer (set via `set_store()`/`set_fetcher()`/`set_vault_writer()`)
- All fetcher methods are async
- Citation verification is mechanical (unicode-normalized, whitespace-collapsed substring match)
- First run stores baseline hash — no extraction on first run
- Graph skips LLM extraction when no change detected (conditional edge)
- Vault writer uses `langchain-mcp-adapters` MultiServerMCPClient → flywheel-memory stdio
- Vault writes enabled by default; `--no-vault` to disable
- Vault deduplication via `canary_run_id` search before writing
- Vault output goes to `~/obsidian/Canary/` (separate from main vault)
- `vault_add_to_section` tool uses `section` parameter (not `heading`)
