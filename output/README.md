# CANARY Output

This folder contains real extraction output from CANARY — not synthetic examples. It holds 453 compliance objectives extracted from 13 regulations across 5 jurisdictions, with 397 of 453 citations (88%) mechanically verified against the published source text.

## Folder Layout

```
output/
└── compliance/
    └── objectives/
        ├── sfdr-l1/              # One folder per regulation
        │   ├── README.md         # Regulation index (verification stats, obligation table)
        │   ├── article-3-1.md    # One file per compliance objective
        │   ├── article-4-1.md
        │   └── ...
        ├── sfdr-rts/
        ├── eu-taxonomy/
        └── ...                   # 13 regulation folders total
```

## Report Types

### Compliance Objective (`compliance-objective`)

Each file represents a single regulatory obligation at the article level.

**What it tells you:** Who must comply, what they must do, where the obligation applies, by when, and how material it is. Every note includes a verbatim quote from the regulation, mechanically checked against the published text.

**Why it matters:** Instead of reading a 40-page regulation to find the obligations relevant to your firm, you get one self-contained file per obligation with structured fields you can filter and triage.

**How to verify manually:**
1. Open any objective file (e.g., [`sfdr-l1/article-8-1.md`](compliance/objectives/sfdr-l1/article-8-1.md))
2. Scroll to the **Legal Basis** section and read the quoted text
3. Check the tag at the end of the quote: `[verified]` or `[unverified]`
4. Open the `source_url` link in your browser
5. Search for the quoted text in the regulation — if the tag says `[verified]`, the quote was found verbatim

**Example:** [`compliance/objectives/sfdr-l1/article-8-1.md`](compliance/objectives/sfdr-l1/article-8-1.md)

### Regulation Index (`regulation-index`)

A README in each regulation folder that acts as a table of contents with verification statistics.

**What it tells you:** How many obligations were extracted from this regulation, how many citations are verified, and a breakdown by obligation type and materiality level. Each row links to the relevant objective, and unverified rows are flagged for human review.

**Why it matters:** Gives you at-a-glance coverage — you can immediately see which regulations have full citation coverage and which have gaps that need manual review.

**How to verify manually:**
1. Open a regulation README (e.g., [`uk-fsa-2023/README.md`](compliance/objectives/uk-fsa-2023/README.md))
2. Check the verified/total count at the top
3. Scan the obligations table — any row marked **UNVERIFIED** requires manual review
4. Click into an individual objective to spot-check the citation

**Example:** [`compliance/objectives/uk-fsa-2023/README.md`](compliance/objectives/uk-fsa-2023/README.md)

### Change Report (`regulatory-change`)

Generated when CANARY detects that a regulation has been amended on EUR-Lex.

**What it tells you:** The severity of the change, which articles are affected, supporting quotes with verification status, and a unique run ID for audit purposes.

**Why it matters:** This is the core monitoring output — the reason CANARY exists. When a regulation changes, you get a structured report instead of discovering the change weeks later during a manual review. The deterministic detection (SHA-256 hash comparison) means no changes are missed.

**How to verify manually:**
1. Check the `severity` and `affects` fields in the frontmatter
2. Read the supporting quotes in the Changes section
3. Check each quote's `[verified]` or `[UNVERIFIED]` tag
4. Open the `source_url` to confirm the change against the published text
5. Use the `canary_run_id` to trace the detection back to a specific pipeline run

**Current status:** No change reports have been generated yet. All 13 monitored regulations have remained unchanged since monitoring began. When a regulation is amended, the change report will appear alongside the compliance objectives.

## Reading the Frontmatter

Every output file starts with YAML frontmatter. Here are the key fields:

| Field | Meaning |
|-------|---------|
| `type` | What kind of file this is: `compliance-objective`, `regulation-index`, or `regulatory-change` |
| `regulation` | Full name of the regulation |
| `article` | The specific article or section this obligation comes from |
| `obligation_type` | Category of obligation: `disclosure`, `governance`, `process`, or `reporting` |
| `materiality` | How significant: `high`, `medium`, or `low` |
| `citation` | Whether the verbatim quote was found in the source text: `verified` or `unverified` |
| `source_url` | Direct link to the regulation on EUR-Lex or the relevant legislative database |
| `canary_run_id` | Unique identifier tying this output to a specific pipeline run (audit trail) |

## Trust Model

Every citation is checked with a deterministic substring match against the published regulation text, with Unicode normalization and whitespace collapsing. This is not a confidence score or an AI judgment — it is a mechanical pass/fail check.

- **`[verified]`** = the exact quote was found in the source text. You can confirm this yourself by opening the `source_url` and searching for the quoted text.
- **`[unverified]`** = the quote was not found verbatim. This requires human review — it may be a paraphrase, a truncation, or from a different consolidation of the regulation.

**Current rate:** 397/453 (88%) verified. See the [main README](../README.md#guarantees-and-trust-model) for the full technical explanation.

## Coverage

| Regulation | Folder | Objectives | Verified | Index |
|------------|--------|-----------|----------|-------|
| SFDR Level 1 | [`sfdr-l1/`](compliance/objectives/sfdr-l1/) | 35 | 34 | -- |
| SFDR RTS | [`sfdr-rts/`](compliance/objectives/sfdr-rts/) | 112 | 100 | -- |
| SFDR 2.0 Proposal | [`sfdr-2-proposal/`](compliance/objectives/sfdr-2-proposal/) | 123 | 88 | -- |
| EU Taxonomy | [`eu-taxonomy/`](compliance/objectives/eu-taxonomy/) | 54 | 54 | -- |
| MiFID II Sustainability | [`mifid-sustainability/`](compliance/objectives/mifid-sustainability/) | 44 | 43 | -- |
| UK FSA 2023 | [`uk-fsa-2023/`](compliance/objectives/uk-fsa-2023/) | 5 | 5 | [README](compliance/objectives/uk-fsa-2023/README.md) |
| UK TCFD Regs 2022 | [`uk-tcfd-regs/`](compliance/objectives/uk-tcfd-regs/) | 10 | 10 | [README](compliance/objectives/uk-tcfd-regs/README.md) |
| UK SDR Regs 2023 | [`uk-sdr-regs/`](compliance/objectives/uk-sdr-regs/) | 10 | 10 | [README](compliance/objectives/uk-sdr-regs/README.md) |
| UK Climate Change Act | [`uk-climate-change/`](compliance/objectives/uk-climate-change/) | 10 | 10 | [README](compliance/objectives/uk-climate-change/README.md) |
| UK Environment Act | [`uk-env-act/`](compliance/objectives/uk-env-act/) | 10 | 6 | [README](compliance/objectives/uk-env-act/README.md) |
| US Sarbanes-Oxley | [`us-sox/`](compliance/objectives/us-sox/) | 10 | 7 | [README](compliance/objectives/us-sox/README.md) |
| NZ FMC Act 2013 | [`nz-fmc-act/`](compliance/objectives/nz-fmc-act/) | 20 | 20 | [README](compliance/objectives/nz-fmc-act/README.md) |
| Irish Companies Act | [`ie-companies-act/`](compliance/objectives/ie-companies-act/) | 10 | 10 | [README](compliance/objectives/ie-companies-act/README.md) |
| **Total** | | **453** | **397 (88%)** | |
