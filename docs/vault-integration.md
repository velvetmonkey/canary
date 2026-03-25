# Vault Integration

[< Back to README](../README.md)

## MCP Connection

`src/canary/output/vault.py` — `VaultWriter`

Connects to the [[Flywheel]] MCP server via `langchain-mcp-adapters` `MultiServerMCPClient` (stdio transport).

### Configuration

| Setting | Default | Env override |
|---------|---------|--------------|
| MCP server path | `~/src/flywheel-memory/packages/mcp-server/dist/index.js` | `CANARY_MCP_SERVER` |
| Vault path | `~/obsidian/Canary` | `FLYWHEEL_VAULT` |
| Writer preset | `writer` | — |

### MCP Tools Used

| Tool | Purpose |
|------|---------|
| `search` | Deduplication — search for `canary_run_id` before writing |
| `vault_create_note` | Write change reports and objective notes |
| `vault_add_to_section` | Append timestamped entries to daily note "Log" section |

### Write Paths

- Change reports: `work/compliance/reports/{date}-{source_id}.md`
- Objectives: `work/compliance/objectives/{regulation_short}/{article-ref}.md` (article sanitized: `Article 4(1)(a)` → `article-4-1-a`)
- Daily log: `daily-notes/{date}.md` → "Log" section, `timestamp-bullet` format

### Deduplication

Before every write, `check_duplicate(run_id)` searches the vault for the `canary_run_id`. If a match is found, the write is skipped entirely.

## Vault Output Structure

```
~/obsidian/Canary/
├── work/compliance/
│   ├── reports/                        # Change detection reports
│   │   └── 2026-03-11-SFDR-L1.md
│   └── objectives/                     # Compliance objectives
│       └── sfdr-l1/
│           ├── article-3-1.md
│           ├── article-4-1.md
│           └── ...
└── daily-notes/
    └── 2026-03-11.md                   # Daily log entries
```

> See [`output/README.md`](../output/README.md) for a non-technical guide to the output.

## Output Formats

### Change report (`regulatory-change`)

Generated when CANARY detects that a monitored regulation has been amended. Contains the severity, affected articles, and supporting quotes with verification status.

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

### Compliance objective (`compliance-objective`)

One note per regulatory obligation. Captures who must comply, what they must do, and a verbatim quote verified against the source text.

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

### Regulation index (`regulation-index`)

A [[README]] per regulation folder — [[Table of Contents]] with verification statistics and coverage breakdown by obligation type and materiality.

```yaml
---
type: regulation-index
regulation: Financial Services and Markets Act 2023 (FSMA 2023)
celex_id: ukpga/2023/29
objectives: 10
verified: 5
updated: 2026-03-18
canary_run_id: obj-97906736fa27
---
```

### Run summary (JSON)

Structured log of each [[Pipelines|pipeline]] run — how many sources were checked, what was detected, and token usage.

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
