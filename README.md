# bpgraph

A [FalkorDB](https://www.falkordb.com/) knowledge graph of protein–protein interactions, human–human and virus–human, and the tooling that builds it. Every interaction carries the publications, detection methods and peptides behind it; proteins are enriched with UniProt function text, GO annotations and the NCBI taxonomy of the viruses; and curated topics — lists of human proteins involved in a subject such as ferroptosis — make it possible to ask how viral families act on a biological process.

This repository holds everything the graph needs, and nothing a client does — querying is only ever through the MCP server:

- **the graph server** — FalkorDB and its browser UI, run with Docker Compose;
- **the ingestion** — a Python package that turns an export of the curation database into a fresh, validated graph;
- **the MCP server** — a read-only endpoint through which Claude and other MCP clients query the graph in Cypher.

Curation itself happens in a separate relational database. The graph is never edited in place: each export is built into a staging graph, checked, and swapped in whole.

## Quick start

Requires Docker and [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env        # set FALKORDB_PASSWORD to enable auth
docker compose up -d
uv sync
```

| service            | port | role                                                    |
| ------------------ | ---- | ------------------------------------------------------- |
| `falkordb-server`  | 6379 | the graph; builds write here over RESP                  |
| `falkordb-browser` | 3000 | UI; log in with host `falkordb-server`, not `localhost` |
| `falkordb-mcp`     | 8080 | MCP at `http://localhost:8080/mcp`, read-only           |

## Building a graph

A run lives in its own directory, `data/<date>/` (gitignored): the TSV files the curation database exports go in `export/`, and what the export lacks is fetched beside it.

```sh
uv run bpgraph-functions data/2026-09-09   # UniProt function text
uv run bpgraph-go data/2026-09-09          # GO terms, ancestry and annotations
```

The build then loads the export into Pydantic models, writes it to `bpgraph_staging`, adds the unique constraints as a validation gate, and renames the result to the live graph `bpgraph`. A malformed export fails before anything is written. See [`docs/build.md`](docs/build.md) for the full sequence and [`docs/export.md`](docs/export.md) for a worked example.

```sh
uv run bpgraph         # what the live graph holds
uv run bpgraph-audit   # check the live graph against the schema
```

## Querying

Point an MCP client at `http://localhost:8080/mcp` and give it [`docs/mcp-client.md`](docs/mcp-client.md), a digest of the schema written for query clients. [`docs/queries.md`](docs/queries.md) has canonical queries and a worked example.

## Documentation

- [`docs/schema.md`](docs/schema.md) — the schema contract. FalkorDB is schemaless; this document is what keeps the graph coherent.
- [`docs/export.md`](docs/export.md) — the TSV files a run ingests.
- [`docs/build.md`](docs/build.md) — building, validating, swapping and auditing a graph.
- [`docs/queries.md`](docs/queries.md) — canonical queries.
- [`docs/mcp-client.md`](docs/mcp-client.md) — the schema digest for MCP clients.
- [`AGENTS.md`](AGENTS.md) — conventions for working on this repository.
