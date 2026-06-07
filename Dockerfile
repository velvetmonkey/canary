# syntax=docker/dockerfile:1
#
# One image for the whole seal x Canary e2e demo (all three repos).
#   docker build -t seal-canary-demo .
#   docker run --rm seal-canary-demo
# Runs fully offline: no ANTHROPIC_API_KEY, no network at run time.
# Prints the P3 report ending in a PASS/FAIL line.
#
# Pins are build args so the image is reproducible; bump them as the repos move.

############################################################
# Stage 1: build the verified `seal` binary (Lean 4)
############################################################
FROM debian:bookworm-slim AS seal-build
ARG MCP_SEAL_REF=d10b626
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*
# elan = the Lean toolchain manager; it auto-installs the version pinned in lean-toolchain
RUN curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y
ENV PATH="/root/.elan/bin:${PATH}"
RUN git clone https://github.com/velvetmonkey/mcp-seal /src/mcp-seal
WORKDIR /src/mcp-seal
RUN git checkout ${MCP_SEAL_REF} && lake build      # -> .lake/build/bin/seal

############################################################
# Stage 2: build the flywheel-memory MCP server (Node)
############################################################
FROM node:22-bookworm-slim AS flywheel-build
ARG FLYWHEEL_REF=de8119e
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/velvetmonkey/flywheel-memory /src/flywheel-memory
WORKDIR /src/flywheel-memory
RUN git checkout ${FLYWHEEL_REF} && npm ci && npm run build

############################################################
# Stage 3: runtime (Node + uv-managed Python 3.12 + Canary)
############################################################
FROM node:22-bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# uv brings its own pinned Python 3.12
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# seal: just the binary + the proof-shot file (not the whole .lake tree)
COPY --from=seal-build /src/mcp-seal/.lake/build/bin/seal /src/mcp-seal/.lake/build/bin/seal
COPY --from=seal-build /src/mcp-seal/Test /src/mcp-seal/Test
# flywheel server: dist + runtime node_modules
COPY --from=flywheel-build /src/flywheel-memory /src/flywheel-memory

# canary = this build context
COPY . /src/canary
WORKDIR /src/canary
RUN uv sync --frozen || uv sync

# run_p3.py also discovers these via sibling layout; set explicitly as belt-and-braces
ENV SEAL_BIN=/src/mcp-seal/.lake/build/bin/seal \
    FLYWHEEL_SERVER=/src/flywheel-memory/packages/mcp-server/dist/index.js \
    NODE_BIN=/usr/local/bin/node

ENTRYPOINT ["uv", "run", "python", "demo/run_p3.py"]
