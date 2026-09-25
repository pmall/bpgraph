# bpgraph

A [FalkorDB](https://www.falkordb.com/) knowledge graph of protein–protein interactions, human–human and virus–human, and the tooling that builds and explores it. Every interaction carries the publications, detection methods and peptides behind it, abstracts included. A viral protein is a curated one — `HBx` of HBV, `NS5A` of HCV — pooled over every strain and UniProt accession it was observed on, so its evidence is counted once rather than scattered; the accessions stay in the graph as the entries each observation used. Proteins are enriched with UniProt function text and GO annotations, viruses are grouped by a curated list and rolled up to their NCBI family, and curated topics — lists of human proteins involved in a subject such as ferroptosis — make it possible to ask how viral families act on a biological process.

The graph is built to be explored by an agent. Scripts do the deterministic work; the agent reads the connected text — function descriptions, GO annotations, abstracts — and draws the connections a person would need years of reading to make.

This repository holds:

- **the graph server** — FalkorDB and its browser UI, run with Docker Compose;
- **the ingestion** — a Python package that turns an export of the curation database into a fresh, validated graph;
- **the MCP server** — read-only tools through which agents explore the graph;
- **the analyses** — skills in `.agents/skills` that pair an analysis's instructions with scripts.

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
| `bpgraph-mcp`      | 8080 | MCP at `http://localhost:8080/mcp`, read-only           |

## Building a graph

A run lives in its own directory, `data/<date>/` (gitignored): the TSV files the curation database exports go in `export/`, and what the export lacks is fetched beside it, each fetch recording its release in `sources.tsv`. The viruses proteins are grouped by are curated in [`curation/viruses.tsv`](curation/viruses.tsv), and [`curation/viruses.md`](curation/viruses.md) explains the choices.

```sh
uv run bpgraph-taxonomy data/2026-09-09    # NCBI taxonomy
uv run bpgraph-functions data/2026-09-09   # UniProt function text
uv run bpgraph-go data/2026-09-09          # GO terms, ancestry and annotations
uv run bpgraph-build data/2026-09-09       # build and publish the graph
```

The build loads the export into Pydantic models, writes it to `bpgraph_staging`, adds the unique constraints as a validation gate, and renames the result to the live graph `bpgraph`. A malformed export, or a viral taxon with no curated virus, fails before anything is written. See [`docs/build.md`](docs/build.md) for the full sequence and [`docs/export.md`](docs/export.md) for a worked example.

```sh
uv run bpgraph         # what the live graph holds
uv run bpgraph-audit   # check the live graph against the schema
```

## Querying

The live graph is the only source of truth; `data/` holds build inputs. Agents query it through the MCP server, whose `query` tool runs read-only Cypher; `.mcp.json` registers it for Claude Code. The same query runs from a terminal. [`docs/queries.md`](docs/queries.md) has the rules, canonical queries and a worked example.

```sh
uv run bpgraph-query "MATCH (t:Topic) RETURN t.name"
```

To draw a subnetwork, gather it into a `network.json` and render it; no database connection is needed. The `network-view` skill in `.agents/skills` describes the file:

```sh
uv run bpgraph-network ferroptosis-flaviviridae.json   # -> ferroptosis-flaviviridae.cytoscape.html
```

## Documentation

- [`docs/schema.md`](docs/schema.md) — the schema contract. FalkorDB is schemaless; this document is what keeps the graph coherent.
- [`docs/export.md`](docs/export.md) — the TSV files a run ingests.
- [`docs/build.md`](docs/build.md) — building, validating, swapping and auditing a graph.
- [`docs/queries.md`](docs/queries.md) — exploring the graph: access, rules, canonical queries.
- [`docs/development.md`](docs/development.md) — code layout, conventions and verification.
- [`AGENTS.md`](AGENTS.md) — conventions for working on this repository.
