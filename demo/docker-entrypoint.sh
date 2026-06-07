#!/bin/sh
# Entrypoint for the seal x Canary P3 demo image.
#
# Runs the demo, then (if a host directory is mounted at /out) copies the
# whole disposable workspace there so the corpus, vault, policy, approvals
# control file and P3-REPORT.md can be inspected from the host AFTER the
# container exits.
#
#   # view artifacts on the host after the run:
#   docker run --rm -v "$(pwd)/demo-out:/out" seal-canary-demo
#
# Note: we copy to /out rather than letting the runner write there directly,
# because run_p3.py rmtree's /tmp/seal-demo-p3 at startup and you cannot
# rmtree a live bind-mount point.
set -e

WORKSPACE="/tmp/seal-demo-p3"

# run the demo without aborting the copy step on a FAIL exit code
set +e
uv run python demo/run_p3.py
status=$?
set -e

if [ -d /out ]; then
    if [ -d "$WORKSPACE" ]; then
        cp -a "$WORKSPACE/." /out/ 2>/dev/null || true
        echo "[entrypoint] workspace copied to /out (host mount) -> view P3-REPORT.md + vault-canary/ there"
    else
        echo "[entrypoint] no workspace at $WORKSPACE to copy"
    fi
else
    echo "[entrypoint] tip: mount a host dir with -v \"\$(pwd)/demo-out:/out\" to keep the artifacts after exit"
fi

exit "$status"
