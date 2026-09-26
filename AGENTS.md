# bpgraph — agent guide

A FalkorDB knowledge graph of protein–protein interactions, human–human and virus–human, rich in text: every interaction is backed by the publications that report it, titles and abstracts included, and proteins carry their UniProt function text and experimental GO annotations, each tied to its publications. A viral protein is a curated one, `HBx` of HBV, pooled over the strains and accessions it was observed on. Scripts do the deterministic work. The agent is the explorer: it reads that connected text and makes the connections a person would need years of reading to make.

This repository both builds the graph and queries it.

## The graph is the source of truth

The live graph `bpgraph` on the FalkorDB server is the only source of truth about the data. `data/` holds the sources a build ingests, not answers.

`docker compose up -d` brings up:

| service            | port | role                                                    |
| ------------------ | ---- | ------------------------------------------------------- |
| `falkordb-server`  | 6379 | the graph                                               |
| `falkordb-browser` | 3000 | UI. Log in with host `falkordb-server`, not `localhost` |
| `bpgraph-mcp`      | 8080 | MCP at `/mcp`: how agents query the graph, read-only    |

`bpgraph` is the live graph key, and `bpgraph_staging` is where a build writes. **Never write to `bpgraph` outside a build swap.** Experiment in a throwaway graph named `_probe` and delete it afterwards. Connection settings come from `.env`, which is gitignored. `.env.example` documents the variables.

[`docs/schema.md`](docs/schema.md) is the schema contract. FalkorDB is schemaless, so that document is the only thing keeping the graph coherent. [`docs/roadmap.md`](docs/roadmap.md) is where it is going: build today's work so it scales to many host species.

## Read according to the task

- **Exploring the graph**, answering a question or running an analysis skill: [`docs/queries.md`](docs/queries.md).
- **Building a graph** or changing what it holds: [`docs/build.md`](docs/build.md) and [`docs/export.md`](docs/export.md).
- **Writing code**, for the build or a skill's script: [`docs/development.md`](docs/development.md).

Analyses that recur are skills in `.agents/skills`. A skill says what to analyse and what to report, and a script gives it a standard entry point for the mechanical part.

## Git

Do not commit unless the current message asks for it. No co-authors.
