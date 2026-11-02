# bpgraph

A [FalkorDB](https://www.falkordb.com/) knowledge graph of protein–protein interactions, human–human and virus–human, built to be explored by an agent. Scripts do the deterministic work; the agent reads the connected text — function descriptions, GO annotations, abstracts — and draws the connections a person would need years of reading to make.

## The data

The human interactome is IntAct's interactions, kept by detection method, with our own curation on top; the virus–human interactions are ours. Every interaction carries the publications, detection methods and peptides behind it, abstracts included. Every Swiss-Prot human protein is in, with its UniProt function text and experimental GO annotations of what it does — biological process and molecular function — each tied to the publications behind it. A viral protein is a curated one — `HBx` of HBV, `NS5A` of HCV — pooled over every strain and UniProt accession it was observed on, so its evidence is counted once rather than scattered; its virus is the species curation groups it under, rolled up to its NCBI family. Curated topics — lists of human proteins involved in a subject such as ferroptosis, which a query takes as a parameter — make it possible to ask how viral families act on a biological process. Sequences live in SQLite vaults beside the graph.

Curation itself happens in a separate relational database. The graph is never edited in place: each run is built from that database's export and from public sources into a staging graph, checked, and swapped in whole. [`graph/docs/schema.md`](graph/docs/schema.md) is what the graph holds, and [`graph/docs/roadmap.md`](graph/docs/roadmap.md) where it is heading: many hosts, sequence and full-text vaults, protein language model features.

## The parts

This repository is a uv workspace of two packages:

- **[`graph/`](graph/README.md)**, the package `bpgraph`: the graph and everything around it — the ingestion that builds it, an internal query API over the graph and its vaults, and the MCP server, the only thing consumers see.
- **[`client/`](client/README.md)**, the package `bpgraph-client`: what a repository consulting the graph needs — its agent's instructions, the analysis skills, and the command that does their mechanical part. It reaches the graph through the MCP server only.

## Running it

Requires Docker and [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env        # set FALKORDB_PASSWORD to enable auth
docker compose up -d
uv sync                     # both packages
```

This brings up the graph, its browser UI at `http://localhost:3000` — log in with host `falkordb-server`, not `localhost` — and the MCP server at `http://localhost:8080/mcp`; `docker-compose.yml` describes each service. [`graph/docs/build.md`](graph/docs/build.md) says how to build a graph, and [`client/README.md`](client/README.md) how to consult it.

[`AGENTS.md`](AGENTS.md) is the guide for agents working on this repository.
