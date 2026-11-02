# bpgraph — the graph

The package `bpgraph`: the knowledge graph of protein–protein interactions, the ingestion that builds it, and the servers that let any team query it. It knows none of its clients.

## Folders

- `src/bpgraph/`, the code: a module per public source a run fetches; `loaders/`, which turn a run's files into the checked files the graph is written from; `write/`, the statements that write it; the build and the audit; `api/`, the internal query API; the MCP server; and `guide/`, what the MCP server sends its agents beyond the tool descriptions.
- `tests/`, the tests of what needs no graph: the docs against the code.
- `curation/`, the curated lists a build reads, each with a document explaining its choices.
- `docs/`, the builder's docs: [`schema.md`](docs/schema.md), the schema contract; [`build.md`](docs/build.md), building a graph; [`development.md`](docs/development.md), changing its code; [`roadmap.md`](docs/roadmap.md), where it is going.
- `Dockerfile`, the image of the query API and the MCP server.

## Commands

The `bpgraph-*` commands fetch the public sources into a run directory, beside the curation database's export, build it into the live graph `bpgraph` and its sequence vaults, audit what was built, query the live graph from a terminal, and serve it: the query API, internal, and the MCP server, read-only, the only thing consumers see. `pyproject.toml` lists them, and each one's `--help` says what it does.
