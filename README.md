# CANARY

[![CI](https://github.com/velvetmonkey/canary/actions/workflows/ci.yml/badge.svg)](https://github.com/velvetmonkey/canary/actions/workflows/ci.yml)

**C**ompliance **AN**alysis and **A**utomated **R**egulatory **Y**ield

CANARY wears two hats:

1. **Host for the `seal` security demo.** It runs a real multi-stage LLM pipeline in front of [seal](https://github.com/velvetmonkey/mcp-seal), a verified MCP approval-gate sidecar, and proves a destructive vault write dies at a gate the model cannot influence. **Start here:** [Security Demo: seal x Canary](#security-demo-seal-x-canary).
2. **A self-teaching LangGraph compliance pipeline.** It monitors financial regulation across 5 jurisdictions, extracts compliance obligations, and mechanically verifies every citation against the source text. The pipeline, the verification engine, and the 487 real extraction artifacts are the substance. See [The Canary Pipeline](#the-canary-pipeline).

## Contents

- [Security Demo: seal x Canary](#security-demo-seal-x-canary)
  - [Two scenarios](#two-scenarios)
  - [Run it in Docker, from scratch (WSL2)](#run-it-in-docker-from-scratch-wsl2)
  - [Experiment with the approval config](#experiment-with-the-approval-config)
  - [Run it natively (no Docker)](#run-it-natively-no-docker)
- [The Canary Pipeline](#the-canary-pipeline)
  - [The Big Idea: Verified Citations](#the-big-idea-verified-citations)
  - [Coverage](#coverage)
  - [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Related repositories](#related-repositories)

---

## Security Demo: seal x Canary

[seal](https://github.com/velvetmonkey/mcp-seal) is a verified MCP approval-gate sidecar. This repo hosts its end-to-end demo: Canary, a genuine LLM pipeline that writes to an Obsidian vault, is run with `seal` sitting in front of the vault's MCP server. The demo proves that a destructive write is gated at a verified boundary the model cannot influence.

The demo runs **fully offline**: no `ANTHROPIC_API_KEY`, no network. The regulation corpus is frozen on disk (`demo/corpus`) and the extraction step is replayed from a fixture, so every run is deterministic.

**Honest claim:** a default-deny gate blocks the destructive action at a verified boundary the model cannot influence, and every allowed action is explicitly approved. It does **not** claim prompt-injection prevention. The model can still be fooled; the demo shows the action dies regardless. Full storyboard and proof shots: [demo/DEMO.md](demo/DEMO.md).

### Two scenarios

The demo has two scenarios, selected by the `SEAL_SCENARIO` environment variable (or `SCENARIO=` via the helper script):

1. **P3 kill/restore** (default, no env). Canary runs through `seal`; the legitimate report `note/create` is approved and lands. Then the destructive `note/delete` is deleted **without** `seal` and **blocked with** `seal`, the file surviving byte-identical.
2. **Approval lifecycle** (`SEAL_SCENARIO=lifecycle`). The write (`note/create`) is approved and lands; the delete (`note/delete`) is blocked while no approval is present, then **allowed** once a trusted approval is written. Detail [below](#scenario-allow-the-write-deny-the-delete-until-approved).

Both scenarios share the same policy sandbox, the same `/out` artifact mount, and the same colour-coded output.

### Run it in Docker, from scratch (WSL2)

The image bundles all three repos (seal + flywheel-memory + canary) and builds them itself, so the only host dependency is Docker. From a clean WSL2 box:

**1. Install Docker.** Either Docker Desktop with WSL integration enabled, or the native engine in the distro:

```bash
curl -fsSL https://get.docker.com | sh    # let the 20s timer run, do NOT Ctrl+C
sudo usermod -aG docker "$USER"
newgrp docker                             # activate the group without a WSL restart
sudo service docker start
docker run --rm hello-world               # smoke test
```

**2. Fix DNS if clones fail.** If `curl` or the in-container `git clone` fail with `Could not resolve host`, a VPN (e.g. Tailscale) is hijacking resolution. Add a working resolver and make it stick:

```bash
echo "nameserver 1.1.1.1" | sudo tee /etc/resolv.conf
printf '[network]\ngenerateResolvConf = false\n' | sudo tee -a /etc/wsl.conf
```

The Docker daemon inherits host DNS, so the in-container clones need this too.

**3. Clone and run, one command.** `demo/run-demo.sh` builds the image if it is missing, runs the demo, mounts the artifacts to `./demo-out`, and tails the report. The first run is slow: it cold-compiles the Lean core. Every run after reuses the image.

```bash
git clone https://github.com/velvetmonkey/canary
cd canary
demo/run-demo.sh
ls demo-out/    # P3-REPORT.md, vault-canary/, demo-policy.json, approvals.ndjson, poisoned-corpus/
```

That is the whole demo. `demo-out/` holds the full disposable workspace: the generated report, the demo vault, the active policy, the approvals control file, and the poisoned corpus.

<details>
<summary>What the script runs under the hood (manual build + run)</summary>

```bash
docker build -t seal-canary-demo .                          # once; slow cold Lean compile
docker run --rm -v "$(pwd)/demo-out:/out" seal-canary-demo  # every run
```

`docker run <image>` does **not** build the image for you, so a bare `docker run seal-canary-demo` on a clean box fails with `pull access denied` (the image is local-only, never pushed to a registry). Build first, or just use `demo/run-demo.sh` which handles it.

Why the `/out` mount rather than binding the workspace directly: the runner rebuilds its workspace at `/tmp/seal-demo-p3` inside the container and wipes it (`rmtree`) on each start, so that path cannot be bind-mounted. The entrypoint copies the workspace to `/out` on exit instead, so it survives `--rm`. Without a mount the demo still runs and prints the report to stdout; artifacts are discarded on exit.
</details>

### Experiment with the approval config

The policy is **not** baked into a rebuild. Mount your own at run time via `SEAL_POLICY` and iterate with zero rebuilds. The helper script wraps build-if-needed + run + mount + report tail:

```bash
demo/run-demo.sh                          # P3 kill/restore, baked default policy
demo/run-demo.sh my-policy.json           # your policy, no rebuild
SCENARIO=lifecycle demo/run-demo.sh       # approval-lifecycle scenario
SEAL_EXTRA_APPROVALS=more.ndjson demo/run-demo.sh my-policy.json
FORCE_BUILD=1 demo/run-demo.sh            # force an image rebuild
```

By hand (equivalent to the custom-policy line above):

```bash
docker run --rm \
  -v "$(pwd)/my-policy.json:/cfg/policy.json:ro" -e SEAL_POLICY=/cfg/policy.json \
  -v "$(pwd)/demo-out:/out" seal-canary-demo
```

Output is colour-coded so the streams are tellable apart at a glance:

- **Runner narration** is bright and tinted per source: Canary pipeline = yellow, seal gate = cyan, with green/red/bold for allowed/blocked/verdict.
- **Server stderr** is dimmed so it recedes: the flywheel-memory server = dim cyan, seal's own logs = dim magenta. (The noisy flywheel startup chatter is the dim cyan block.)

Colour is on when stdout is a TTY or when `FORCE_COLOR=1` is set (the helper sets it); `NO_COLOR=1` disables it.

#### Writing a policy

A policy is JSON: an `approval` block (`ttl_seconds`; the control file is forced to the workspace automatically) and a list of `tools`. Each tool rule has a `mode`, a `match` rule, and a capability `target`.

**seal v1 has two modes only: `guarded` and `deny`.** There is no bare `allow` mode. Anything not matched by a guarded rule is denied by default, so "allowed" always means *guarded and carrying a valid approval in the control file*. That is the honest security claim, not a loophole.

`seal` also matches rules by tool **name**, first match wins. Two rules for the same tool name shadow each other; to gate two actions of one tool, use a single rule and derive the `target` from an argument (see the lifecycle scenario).

The baked default guards `note/create`:

```json
{
  "approval": { "ttl_seconds": 120 },
  "tools": [
    { "name": "note", "mode": "guarded",
      "match": { "type": "contains_any_ci", "arg": "action", "needles": ["create"] },
      "target": [ {"literal": "flywheel"}, {"literal": "note"}, {"literal": "create"} ] }
  ]
}
```

Try flipping `mode` to `deny`, gating `delete` instead of `create`, or changing `ttl_seconds`. The verdict (`PASS`/`FAIL`) and the full trace land in `demo-out/P3-REPORT.md`. A policy that denies or allows the probe outright is handled cleanly: the runner skips the approval seed and reports what the policy actually did, rather than erroring.

`SEAL_EXTRA_APPROVALS` points at a file of newline-delimited approval records (`{"target": "<digits>"}` per line) appended on top of the auto-seeded create approval, for pre-approving extra targets you have gated.

#### Scenario: allow the write, deny the delete until approved

`SCENARIO=lifecycle` (env `SEAL_SCENARIO=lifecycle`) runs the approval-lifecycle scenario instead of kill/restore:

1. **Write** (`note/create`) is approved and lands.
2. **Delete** (`note/delete`) is attempted with **no** approval and is blocked; the note survives.
3. A trusted approval for the delete is then written, and the same delete is attempted again and **succeeds**.

It uses a single `note` rule guarding both actions, with the approval target derived from the `action` arg, so create and delete carry **distinct** approval tokens: approving one never approves the other.

### Run it natively (no Docker)

If you have the toolchain (the built `seal` binary, Node, and the Flywheel MCP server as sibling repos, plus `uv`), you can skip Docker:

```bash
uv run python demo/run_p3.py                    # P3 kill/restore
SEAL_SCENARIO=lifecycle uv run python demo/run_p3.py
```

The runner discovers the dependencies via the sibling repo layout, or via the `SEAL_BIN`, `NODE_BIN` and `FLYWHEEL_SERVER` environment overrides.

**seal itself is a single native binary with no Docker dependency.** The container exists only to pull the multi-repo demo together reproducibly. Adoption is a one-line host config change, not a container.

---

## The Canary Pipeline

> **About this project.** CANARY is a self-teaching exercise in building a LangGraph/LangChain processing graph. The goal was to learn how to wire a multi-stage LLM pipeline with typed state, conditional edges, structured extraction, and mechanical verification, applied to a real domain (ESG regulatory compliance) rather than a toy problem. The pipeline, the verification engine, and the 487 real extraction artifacts are the interesting parts.

A LangGraph pipeline that monitors financial regulation across 5 jurisdictions: fetches changes, extracts compliance obligations, mechanically verifies every citation, and delivers audit-ready reports.

### What It Does

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

### The Big Idea: Verified Citations

LLMs make things up. Ask Claude to quote a regulation and it might give you something that *sounds* right but doesn't actually appear in the document. In a compliance context, that's dangerous.

**CANARY checks every single quote.** After Claude extracts an obligation and provides a supporting quote, CANARY takes that quote and searches for it in the actual published regulation text. Not with AI — with a straight substring match. Either the quote is in the document or it isn't.

- **`[verified]`** — the quote was found word-for-word in the real regulation. You can open the source URL and Ctrl+F it yourself.
- **`[unverified]`** — the quote wasn't found. It gets flagged for human review. It is never silently accepted.

This is harder than it sounds. Legal databases use different quote characters (`"` vs `"`), invisible Unicode spaces, footnote markers jammed into the text, and ligatures from PDF conversion. A naive string search fails on perfectly correct quotes. So CANARY normalizes both the quote and the source text first (smart quotes → ASCII, dashes → hyphens, invisible characters stripped, whitespace collapsed) and tries 5 matching strategies before giving up. When all 5 fail, a re-quote pipeline asks Claude to find the exact passage again and re-verifies.

**Result: 431 of 487 citations (89%) verified** across 13 regulations and 5 jurisdictions. See [Citation Verification](docs/citation-verification.md) for the full technical detail.

### What the Output Looks Like

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

## Obligation                               <-- Claude's plain-English summary

**Who:** Financial market participants
**What:** For each financial product that    <-- Claude reads the legal text and
promotes environmental or social                 explains what it actually means
characteristics (Article 8 fund), include        in normal words
in pre-contractual disclosures: (a) info
on how those characteristics are met...
**Where:** In pre-contractual disclosures
**Deadline:** 10 March 2021
**Materiality:** high

## Legal Basis                              <-- the proof

> Where a financial product promotes,       <-- this is copied verbatim from the
> among other characteristics,                   real regulation on EUR-Lex.
> environmental or social characteristics,       CANARY searched the actual
> or a combination of those                      published document and confirmed
> characteristics, provided that the             this exact text exists there.
> companies in which the investments             that's what [verified] means.
> are made follow good governance
> practices, the information to be
> disclosed pursuant to Article 6(1)
> and (3) shall include the following...

*Article 8(1), Regulation (EU) 2019/2088 (SFDR)* [verified]
```

So in each objective: the **Obligation** section is Claude explaining the law in plain English. The **Legal Basis** section is the actual verbatim quote from the published regulation that backs it up — and `[verified]` means CANARY confirmed that quote really exists in the source document.

**487 objectives** extracted from 13 regulations. Browse them: [`output/`](output/) | Guide: [`output/README.md`](output/README.md)

### Why It's Interesting

| Aspect | What CANARY does | Why it matters |
|--------|-----------------|----------------|
| **Citation verification** | 5-strategy mechanical matching with NFKC normalization, smart quote folding, dash normalization, footnote stripping | Every quote is provably present in the source document. 89% verified rate across 487 citations. |
| **Change detection** | SHA-256 hashing — identical documents always hash identically | Zero false positives. No probabilistic thresholds. |
| **Structured extraction** | Pydantic schema enforcement on Claude output | No malformed JSON, no missing fields, no hallucinated enums. Downstream code receives guaranteed-correct objects. |
| **Conditional execution** | LangGraph conditional edge skips LLM when nothing changed | Most runs consume zero tokens. Economically viable at hourly frequency. |
| **Audit trail** | SQLite `run_log` + `source_check_log` + `change_log`, timestamped | Answers "when did you become aware of this change?" with forensic precision. |
| **Re-quote pipeline** | Auto-repairs failed citations by asking Claude to find the exact passage | Unverified quotes are never silently accepted — flagged or repaired. |

### Coverage

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

### Quick Start

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

## Related repositories

Part of the velvetmonkey verified-cognition stack:

- **canary** (this repo) — the LangGraph compliance pipeline and host for the seal demo.
- [mcp-seal](https://github.com/velvetmonkey/mcp-seal) — the verified MCP approval-gate sidecar the demo puts in front of the vault.
- [flywheel-memory](https://github.com/velvetmonkey/flywheel-memory) — the knowledge-graph MCP server Canary writes to, and the server `seal` gates in the demo.

## License

Copyright (c) 2026 velvetmonkey. All rights reserved. See [LICENSE](LICENSE).
