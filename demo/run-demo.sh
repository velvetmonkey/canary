#!/usr/bin/env bash
# Build (if needed) and run the seal x Canary P3 demo, with artifacts mounted
# to ./demo-out on the host. Designed for fast iteration on the approval config.
#
# Usage:
#   demo/run-demo.sh                      # default baked policy (P3 kill/restore)
#   demo/run-demo.sh my-policy.json       # experiment with a custom policy
#   SCENARIO=lifecycle demo/run-demo.sh   # allow write, deny delete until approved
#   SEAL_EXTRA_APPROVALS=more.ndjson demo/run-demo.sh my-policy.json
#   FORCE_BUILD=1 demo/run-demo.sh        # rebuild the image even if it exists
#
# The image is only rebuilt when missing or FORCE_BUILD=1. Policy changes need
# NO rebuild: the policy file is mounted into the container at run time.
set -euo pipefail

IMAGE="${IMAGE:-seal-canary-demo}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"   # canary repo root
OUT="${OUT:-$HERE/demo-out}"
POLICY="${1:-}"

cd "$HERE"

if [ -n "${FORCE_BUILD:-}" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "==> building $IMAGE (this is slow the first time: it compiles the Lean core)"
    docker build -t "$IMAGE" .
else
    echo "==> reusing existing image $IMAGE (set FORCE_BUILD=1 to rebuild)"
fi

mkdir -p "$OUT"
args=(--rm -e FORCE_COLOR=1 -v "$OUT:/out")

if [ -n "${SCENARIO:-}" ]; then
    args+=(-e "SEAL_SCENARIO=$SCENARIO")
    echo "==> scenario: $SCENARIO"
fi

if [ -n "$POLICY" ]; then
    [ -f "$POLICY" ] || { echo "policy file not found: $POLICY" >&2; exit 1; }
    POLICY_ABS="$(cd "$(dirname "$POLICY")" && pwd)/$(basename "$POLICY")"
    args+=(-v "$POLICY_ABS:/cfg/policy.json:ro" -e SEAL_POLICY=/cfg/policy.json)
    echo "==> using custom policy: $POLICY_ABS"
fi

if [ -n "${SEAL_EXTRA_APPROVALS:-}" ]; then
    EXTRA_ABS="$(cd "$(dirname "$SEAL_EXTRA_APPROVALS")" && pwd)/$(basename "$SEAL_EXTRA_APPROVALS")"
    args+=(-v "$EXTRA_ABS:/cfg/extra-approvals.ndjson:ro" -e SEAL_EXTRA_APPROVALS=/cfg/extra-approvals.ndjson)
    echo "==> seeding extra approvals: $EXTRA_ABS"
fi

echo "==> running demo"
docker run "${args[@]}" "$IMAGE"

echo
echo "==> artifacts in $OUT:"
ls -1 "$OUT"
echo "==> report: $OUT/P3-REPORT.md (tail)"
tail -n 3 "$OUT/P3-REPORT.md" 2>/dev/null || true
