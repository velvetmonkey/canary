# CANARY

ESG regulatory change monitoring agent. Watches regulatory sources, detects document changes via content hashing, uses Claude to extract structured regulatory changes, and verifies citations mechanically.

## Phase 1 — EUR-Lex SFDR

Monitors three SFDR documents on EUR-Lex:
- **SFDR Level 1** — Reg (EU) 2019/2088
- **SFDR RTS** — Delegated Reg (EU) 2022/1288
- **SFDR 2.0 Proposal** — COM(2025) 841

## Setup

```bash
uv sync
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env
```

## Usage

```bash
# Run the full pipeline
uv run python -m canary.scheduler

# Run tests (no LLM/network required)
uv run pytest -m "not integration and not llm"

# Run integration tests (hits live EUR-Lex)
uv run pytest -m integration

# Lint
uv run ruff check src/ tests/
```

## Architecture

```
fetch_source → detect_change → [if changed] → extract_obligations → verify_citations → output_results
```

- **Fetcher**: httpx async client with rate limiting, retry, ETag caching
- **Detection**: SHA-256 hash comparison + unified diff
- **Extraction**: Claude Sonnet with Pydantic structured output
- **Verification**: Mechanical citation checking (verbatim quote matching)
- **Output**: JSON + Markdown change reports to console

## Stack

- LangGraph orchestration
- Claude Sonnet via langchain-anthropic
- SQLite for document state + change history
- Pydantic v2 structured output
- httpx + tenacity for reliable fetching
