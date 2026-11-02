# The query API and the MCP server, one image, the MCP by default. Only what
# serving needs: the graph package, locked, no dev tools. Built from the root of
# the workspace, whose lock covers both packages: uv reads every member's
# pyproject.toml, so the client's comes in too, its code never.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
COPY graph/pyproject.toml ./graph/
COPY client/pyproject.toml ./client/
RUN uv sync --locked --no-dev --package bpgraph --no-install-workspace
COPY graph/src ./graph/src
RUN uv sync --locked --no-dev --package bpgraph

CMD ["uv", "run", "--no-sync", "bpgraph-mcp"]
