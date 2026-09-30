# The query API and the MCP server, one image, the MCP by default. Only what
# serving needs: the package, locked, no dev tools, and the schema the API
# serves.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY docs/schema.md ./docs/schema.md
RUN uv sync --locked --no-dev

CMD ["uv", "run", "--no-sync", "bpgraph-mcp"]
