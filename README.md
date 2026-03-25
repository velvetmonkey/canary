# CANARY

[![CI](https://github.com/velvetmonkey/canary/actions/workflows/ci.yml/badge.svg)](https://github.com/velvetmonkey/canary/actions/workflows/ci.yml)

**C**ompliance **AN**alysis and **A**utomated **R**egulatory **Y**ield

A LangGraph pipeline that monitors financial regulation across 5 jurisdictions — fetches changes, extracts compliance obligations, mechanically verifies every citation, and delivers audit-ready reports.

> **About this project.** CANARY is a self-teaching exercise in building a LangGraph/LangChain processing graph. The goal was to learn how to wire a multi-stage LLM pipeline with typed state, conditional edges, structured extraction, and mechanical verification — applied to a real domain (ESG regulatory compliance) rather than a toy problem. The pipeline, the verification engine, and the 487 real extraction artifacts are the interesting parts.

## What It Does

```
EUR-Lex/UK Legislation/GovInfo → fetch → detect → extract → verify → report → vault
                                  httpx   SHA-256  Claude   substring markdown  Flywheel
                                  retry   difflib  Pydantic matching   YAML FM    MCP
```

1. **Fetch** regulation text from 5 government legal databases (EUR-Lex, UK Legislation, GovInfo, NZ Legislation, Irish Statute Book)
2. **Detect** changes via SHA-256 hash comparison — deterministic, zero false positives
3. **Extract** structured obligations using Claude with Pydantic schema enforcement — not free-text, not JSON-maybe
4. **Verify** every extracted citation against the source text using 5 matching strategies with full Unicode normalization
5. **Report** as structured markdown with YAML frontmatter, ready for compliance triage
6. **Store** in an Obsidian vault via MCP, with full SQLite audit trail

The key LangGraph insight: a conditional edge after `detect_change` skips the LLM entirely when nothing changed. Most runs cost nothing. This makes hourly monitoring of 14 sources economically viable (~$0.05/run, ~15s total).

## The Big Idea: Verified Citations

LLMs make things up. Ask Claude to quote a regulation and it might give you something that *sounds* right but doesn't actually appear in the document. In a compliance context, that's dangerous.

**CANARY checks every single quote.** After Claude extracts an obligation and provides a supporting quote, CANARY takes that quote and searches for it in the actual published regulation text. Not with AI — with a straight substring match. Either the quote is in the document or it isn't.

- **`[verified]`** — the quote was found word-for-word in the real regulation. You can open the source URL and Ctrl+F it yourself.
- **`[unverified]`** — the quote wasn't found. It gets flagged for human review. It is never silently accepted.

This is harder than it sounds. Legal databases use different quote characters (`"` vs `"`), invisible Unicode spaces, footnote markers jammed into the text, and ligatures from PDF conversion. A naive string search fails on perfectly correct quotes. So CANARY normalizes both the quote and the source text first (smart quotes → ASCII, dashes → hyphens, invisible characters stripped, whitespace collapsed) and tries 5 matching strategies before giving up. When all 5 fail, a re-quote pipeline asks Claude to find the exact passage again and re-verifies.

**Result: 431 of 487 citations (89%) verified** across 13 regulations and 5 jurisdictions. See [Citation Verification](docs/citation-verification.md) for the full technical detail.

## What the Output Looks Like

Each objective is a self-contained markdown file — structured frontmatter for filtering, a plain-English obligation breakdown, and a **verified legal quote** you can trace back to the source:

```yaml
---
type: compliance-objective
regulation: Regulation (EU) 2019/2088 (SFDR)
article: "Article 8(1)"
obligation_type: disclosure
materiality: high
citation: verified                          # <-- mechanically checked
source_url: https://eur-lex.europa.eu/...   # <-- go verify it yourself
canary_run_id: obj-fb4c37ee3772
---
```

```markdown
# Article 8(1) — Pre-contractual disclosure for Article 8 products

## Obligation

**Who:** Financial market participants
**What:** For each financial product that promotes environmental or social
characteristics (Article 8 fund), include in pre-contractual disclosures:
(a) information on how those characteristics are met, and (b) if an index
is designated as a reference benchmark, whether and how that index is
consistent with those characteristics.
**Where:** In pre-contractual disclosures
**Deadline:** 10 March 2021
**Materiality:** high

## Legal Basis                              <-- the actual quote from the law

> Where a financial product promotes, among other characteristics,
> environmental or social characteristics, or a combination of those
> characteristics, provided that the companies in which the investments
> are made follow good governance practices, the information to be
> disclosed pursuant to Article 6(1) and (3) shall include the following...

*Article 8(1), Regulation (EU) 2019/2088 (SFDR)* [verified]   <-- CANARY found
                                                                   this quote in
                                                                   the real document
```

**487 objectives** extracted from 13 regulations. Browse them: [`output/`](output/) | Guide: [`output/README.md`](output/README.md)

## Why It's Interesting

| Aspect | What CANARY does | Why it matters |
|--------|-----------------|----------------|
| **Citation verification** | 5-strategy mechanical matching with NFKC normalization, smart quote folding, dash normalization, footnote stripping | Every quote is provably present in the source document. 89% verified rate across 487 citations. |
| **Change detection** | SHA-256 hashing — identical documents always hash identically | Zero false positives. No probabilistic thresholds. |
| **Structured extraction** | Pydantic schema enforcement on Claude output | No malformed JSON, no missing fields, no hallucinated enums. Downstream code receives guaranteed-correct objects. |
| **Conditional execution** | LangGraph conditional edge skips LLM when nothing changed | Most runs consume zero tokens. Economically viable at hourly frequency. |
| **Audit trail** | SQLite `run_log` + `source_check_log` + `change_log`, timestamped | Answers "when did you become aware of this change?" with forensic precision. |
| **Re-quote pipeline** | Auto-repairs failed citations by asking Claude to find the exact passage | Unverified quotes are never silently accepted — flagged or repaired. |

## Coverage

| Source | Regulation | Objectives | Verified |
|--------|-----------|-----------|----------|
| `SFDR-L1` | SFDR Level 1 — Reg (EU) 2019/2088 | 35 | 34 |
| `SFDR-RTS` | SFDR RTS — Delegated Reg (EU) 2022/1288 | 112 | 100 |
| `SFDR-2-PROPOSAL` | SFDR 2.0 Amendment Proposal (Nov 2025) | 123 | 88 |
| `EU-TAXONOMY` | EU Taxonomy Regulation (EU) 2020/852 | 54 | 54 |
| `MIFID-SUSTAINABILITY` | MiFID II Sustainability Preferences | 44 | 43 |
| `UK-FSA-2023` | UK Financial Services and Markets Act 2023 | 5 | 5 |
| `UK-TCFD-REGS` | UK Climate-Related Financial Disclosures Regs 2022 | 10 | 10 |
| `UK-SDR-REGS` | UK Sustainability Disclosure Requirements Regs 2023 | 10 | 10 |
| `UK-CLIMATE-CHANGE` | UK Climate Change Act 2008 | 10 | 10 |
| `UK-ENV-ACT` | UK Environment Act 2021 | 10 | 6 |
| `US-SOX` | US Sarbanes-Oxley Act 2002 | 44 | 41 |
| `NZ-FMC-ACT` | NZ Financial Markets Conduct Act 2013 | 20 | 20 |
| `IE-COMPANIES-ACT` | Irish Companies Act 2014 | 10 | 10 |
| | | **487** | **431 (89%)** |

Data sources: EUR-Lex (EU), legislation.gov.uk (UK), GovInfo (US), legislation.govt.nz (NZ), irishstatutebook.ie (IE). Full config: [`config/sources.yaml`](config/sources.yaml).

## Quick Start

```bash
git clone git@github.com:velvetmonkey/canary.git && cd canary
uv sync
cp .env.example .env  # add ANTHROPIC_API_KEY

uv run canary                                    # change detection (all sources)
uv run canary extract-objectives --source SFDR-L1 # extract obligations
uv run canary --no-vault                         # console only, no vault writes
uv run canary status                             # recent run history
```

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/architecture.md) | LangGraph pipeline, node responsibilities, state model, Pydantic data models |
| [Citation Verification](docs/citation-verification.md) | 5-strategy matching, Unicode normalization, re-quote pipeline |
| [Extraction](docs/extraction.md) | Chunked extraction, EUR-Lex fetcher, HTML parsing |
| [Storage & Audit](docs/storage-and-audit.md) | SQLite schema, observability, LangSmith tracing, issue tracking |
| [Vault Integration](docs/vault-integration.md) | MCP connection, write paths, output formats, deduplication |
| [Operations](docs/operations.md) | Quick start, all CLI commands, configuration, environment, testing |
| [Technology](docs/technology.md) | Rationale behind each technology choice |
| [Independent Review](docs/review.md) | Third-party code and product assessment |

## Technology Stack

| Layer | Technology | Role |
|-------|-----------|------|
| Orchestration | LangGraph | State machine with conditional edges and checkpointing |
| Extraction | Claude + Pydantic | Structured output with schema enforcement |
| Verification | Substring matching + Unicode normalization | Mechanical citation verification (5 strategies) |
| Change detection | SHA-256 + difflib | Deterministic hashing, unified diffs |
| Fetching | httpx + tenacity | Async HTTP, ETag caching, exponential backoff |
| HTML parsing | BeautifulSoup + lxml | Tolerant legal HTML extraction |
| Vault | MCP + Flywheel | Obsidian integration, idempotent writes |
| Audit | SQLite | Full run provenance, structured exit codes |
| Testing | pytest (91 tests) + ruff | Async tests, full pipeline E2E coverage |

See [Technology](docs/technology.md) for the full rationale behind each choice.

## Roadmap

- Compliance matrix RAG — cross-reference extracted objectives against firm policies
- More sources — SEC rules, FCA Handbook, BaFin, ESMA Q&A
- Scheduling — automated periodic runs via systemd/cron
- Alerting — Slack/email notifications on change detection
- Obligation tracking dashboard

## License

Copyright (c) 2026 velvetmonkey. All rights reserved. See [LICENSE](LICENSE).
