# Technology Stack

[< Back to README](../README.md)

Most RegTech tools are black boxes — opaque SaaS platforms where you trust the vendor's AI output and hope for the best. CANARY takes the opposite approach: every technology choice is made to maximise verifiability, auditability, and transparency. The stack is designed so that AI output is mechanically verified where possible and always published with full provenance for human triage — not silently trusted.

## Pipeline Orchestration — LangGraph

Regulatory monitoring isn't a single [[API Management|API]] call — it's a multi-stage pipeline where each stage has different failure modes and different cost profiles. LangGraph models this as an explicit state machine with typed state, conditional edges, and built-in checkpointing.

The key insight: **most runs cost nothing**. When a regulation hasn't changed (the common case), a conditional edge after `detect_change` skips the LLM entirely — no tokens consumed, no latency, no cost. Only genuine changes trigger extraction. This makes it economically viable to check 14 sources every hour rather than once a week.

Each node is a pure function over the shared state, independently testable with no mocking required. Adding a new pipeline stage (e.g., a future RAG compliance-gap check) means adding one node and one edge — the rest of the pipeline is untouched.

Checkpoint persistence via `langgraph-checkpoint-sqlite` means a crash mid-pipeline doesn't lose work. Re-running picks up from the last successful node.

## Structured Extraction — Claude + Pydantic

LLM output in a compliance context is dangerous if unstructured. A free-text summary might miss an affected article, hallucinate a deadline, or invent a quote. CANARY eliminates this by using Claude's structured output mode with Pydantic schema enforcement.

Every extraction call returns a typed `ExtractionResult` or `ObjectiveExtraction` — not prose, not JSON that might be malformed, but a validated Python object where every field has a defined type, every enum is constrained, and missing fields are caught at the boundary. If Claude returns something that doesn't conform to the schema, the call fails loudly rather than propagating bad data.

The `langchain-anthropic` bridge handles the mechanics: generating the JSON schema from Pydantic models, enforcing output structure, retrying on malformed responses, and coercing edge-case types. The result is that downstream code never needs to validate or parse — it receives guaranteed-correct objects.

## Citation Verification — Mechanical Substring Matching

This is the layer that makes CANARY trustworthy in a way that most AI tools are not. Every supporting quote extracted by Claude is mechanically checked against the source text — no trust, no probability thresholds, just deterministic string matching.

The verification pipeline applies 5 strategies with full Unicode normalization (NFKC, smart quote folding, dash normalisation, invisible character stripping, footnote marker removal). This handles the reality of legal text: EUR-Lex uses different quote characters across consolidations, PDF-to-HTML conversion introduces ligatures and non-breaking spaces, and footnote markers appear inline. A naive substring check would fail on clean, correct quotes.

When verification fails, the re-quote pipeline automatically asks Claude to find the exact passage again — and re-verifies the corrected quote. Unverified citations are never silently accepted; they're flagged in the output for human review. The report publishes regardless — flagging is informational, not a gate.

The outcome: when a compliance report says *"Article 8(1) requires..."* with a supporting quote, that quote is **provably present** in the source document. An auditor can verify it mechanically.

## Change Detection — SHA-256 Hashing + Difflib

Regulatory change detection must have **zero false positives**. A false alert wastes analyst time and erodes trust in the system. CANARY uses SHA-256 hashing — identical documents always produce identical hashes, and any change, no matter how small, produces a different hash. No probabilistic thresholds, no fuzzy matching, no "confidence scores."

When a change is detected, `difflib` generates a unified diff showing exactly what changed. This diff is sent to Claude alongside the full source text, focusing the LLM's attention on the actual changes rather than asking it to re-analyse an entire regulation.

## Async Fetching — httpx + tenacity

Government legal databases are unreliable. EUR-Lex returns 429s under load, legislation.gov.uk has variable response times, and connection resets happen without warning. The fetcher layer is built for this reality.

`httpx` provides native async HTTP with HTTP/2, connection pooling, and ETag caching — so unchanged documents aren't re-downloaded at all. `tenacity` wraps every fetch in declarative retry policies with exponential backoff (4–60s), respecting `Retry-After` headers on 429 responses. Rate limiting (2s between requests) keeps CANARY well under abuse thresholds.

The result: 14 sources across 5 jurisdictions complete in ~15 seconds total, and transient failures are handled automatically without human intervention.

## HTML Extraction — BeautifulSoup + lxml

Legal HTML is messy. EUR-Lex HTML varies significantly across document types — proposals look different from consolidated regulations, annexes have different structures, and PDF-to-HTML conversions introduce artifacts. `lxml` is the fastest Python HTML parser; BeautifulSoup provides a tolerant, forgiving API on top that doesn't break on malformed markup.

The extraction layer strips navigation chrome, headers, footers, and — critically — inline footnote reference tags that render as `( N )` and break citation matching. `get_text()` is called without a separator to preserve the original whitespace structure, avoiding word splits across `<span>` elements in converted documents.

## Vault Integration — MCP + Flywheel

Compliance output that lives in a PDF or email thread is effectively dead. CANARY writes directly to an Obsidian vault via the Model Context Protocol (MCP), turning every change report and compliance objective into a structured, queryable, cross-linked note.

Each note carries YAML frontmatter (regulation, severity, affected articles, materiality, citation status, run ID) that Obsidian can query, filter, and dashboard. Wikilinks connect objectives to their source regulations, and [[Flywheel]]'s entity graph means searching for "SFDR Article 8" surfaces every related obligation, change report, and daily log entry.

Writes are idempotent — before every write, CANARY searches the vault for the `canary_run_id`. If found, the write is skipped. The same run never writes twice.

## Audit Trail — SQLite

Every pipeline run is recorded in SQLite with full provenance: timestamps, token counts, citation statistics, error details, per-source status, and cost estimates. This isn't logging for debugging — it's an audit trail designed to answer the question regulators actually ask: *"When did you become aware of this change, and what did you do about it?"*

Three tables (`run_log`, `source_check_log`, `change_log`) capture the full lifecycle. Structured exit codes (0 = clean, 1 = warnings like unverified citations, 2 = errors like fetch failures) make CI integration straightforward. Issue files in `data/issues/` provide forensic detail when something goes wrong. `canary status` gives a human-readable summary of recent activity.

## Dev Tooling

`pytest` + `pytest-asyncio` + `pytest-httpx` for 91 unit tests covering every pipeline stage, verification strategy, and edge case. `ruff` for linting. `uv` for dependency management — fast, deterministic, lockfile-based.
