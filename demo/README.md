# Seal x Canary Demo Corpus

This directory contains the frozen SFDR Level 1 corpus for the seal x Canary
demo. The regulation fetch step is replayed from disk through `FixtureFetcher`,
so the demo does not depend on live EUR-Lex availability.

Contents:

- `corpus/sources/sfdr-l1.html`: frozen `fetch_text("32019R2088")` output.
- `corpus/objectives/sfdr-l1/`: five curated SFDR objective notes for Articles
  4, 6, 8, and 9.

Run the offline Canary pipeline against a disposable vault:

```bash
rm -rf /tmp/seal-demo-p2
mkdir -p /tmp/seal-demo-p2/vault

PATH="/home/ben/.nvm/versions/node/v22.22.0/bin:$PATH" \
CANARY_FIXTURE_DIR=/home/ben/src/canary/demo/corpus \
CANARY_DB_PATH=/tmp/seal-demo-p2/canary.db \
FLYWHEEL_VAULT=/tmp/seal-demo-p2/vault \
CANARY_OUTPUT_ROOT=work/compliance \
uv run canary --source SFDR-L1
```

For a full change-report demo, seed the disposable database with an older
fixture first, then rerun with `CANARY_FIXTURE_DIR` pointed at this directory.
The normal graph, extraction, verification, output, and MCP write path are
unchanged.
