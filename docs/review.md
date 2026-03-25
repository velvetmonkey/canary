# Independent Code Review (Grok)

[< Back to README](../README.md)

*The following review was produced by Grok after examining the public repository, codebase, and documentation.*

## Product Assessment

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
- Obsidian/[[Flywheel]] dependency (great if you're in that ecosystem; optional plain JSON/Markdown export would broaden appeal).

**Market fit:** Strong for EU sustainable finance teams, asset managers, consultants. No direct competitor combines hash-based change detection + mechanical verification + Obsidian MCP output this cleanly.

## Code Assessment

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
