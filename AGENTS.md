# bpgraph — agent guide

A FalkorDB knowledge graph of protein–protein interactions, human–human and virus–human, rich in text: every interaction is backed by the publications that report it, titles and abstracts included, and proteins carry their UniProt function text and experimental GO annotations of what they do, each tied to its publications. A viral protein is a curated one, `HBx` of HBV, pooled over the strains and accessions it was observed on. Scripts do the deterministic work. The agent is the explorer: it reads that connected text and makes the connections a person would need years of reading to make.

This repository builds the graph and serves it. It does not explore it: consulting repositories do, through the MCP server alone.

## Where things are

The repository is a uv workspace of two packages, each standing alone with its code, docs and processes; the root only runs their tools together. The graph is made for any team and is unaware of our client: nothing in `graph/` imports or names a concept of `client/` (its instructions, its skills, the golden dataset). The client is made for the graph and uses what the MCP server says freely, but never imports `bpgraph`: it reaches the graph only through the MCP server's tools. A ruff rule bans the import both ways.

- `graph/`: the graph and everything around it, the package `bpgraph` and its `bpgraph-*` commands: `graph/src/bpgraph/`, the build, the query API and the MCP server; `graph/curation/`, the curated lists a build reads; `graph/docs/`, the builder's docs; `graph/Dockerfile`, the image of the query API and the MCP server. What any team's queries need travels with the MCP server, never one team's conventions, so every agent gets it without reading a file: its instructions, `graph/src/bpgraph/guide/server.md`, kept under the 2,048 characters Claude Code passes on; the tool descriptions; and the `schema` tool, which returns `graph/src/bpgraph/guide/schema.md`: the graph as a client sees it, written for clients and kept apart from the builder's contract, `graph/docs/schema.md`.
- `client/`: what a repository consulting the graph needs, the package `bpgraph-client`: `client/instructions.md`, which becomes the consulting repository's `AGENTS.md` and holds our rules for every query, the golden dataset, deterministic work in one agent and exploration fanned out to subagents; `client/skills/`, the analyses that recur, which `.agents/skills` and `.claude/skills` link to; `client/src/bpgraph_client/`, the `bpgraph-client` command, the mechanical part of the skills; `client/tests/`, its tests; `client/docs/development.md`, its layout and how a consulting repository installs it. A skill says what to analyse and what to report, and a `bpgraph-client` subcommand gives it a standard entry point for the mechanical part.
- The root: the workspace, `pyproject.toml` and `uv.lock`; `docker-compose.yml` and `.env`, which run the services; `data/`, the runs a build reads and the vaults of the live graph, gitignored.

## The graph is the source of truth

The live graph `bpgraph` on the FalkorDB server is the only source of truth about the data. `data/` holds the sources a build ingests, not answers.

`docker compose up -d` brings up:

| service            | port | role                                                    |
| ------------------ | ---- | ------------------------------------------------------- |
| `falkordb-server`  | 6379 | the graph                                               |
| `falkordb-browser` | 3000 | UI. Log in with host `falkordb-server`, not `localhost` |
| `bpgraph-api`      | —    | query API, internal: schema, Cypher, vault lookups      |
| `bpgraph-mcp`      | 8080 | MCP at `/mcp`: the API's endpoints as tools, read-only  |

`bpgraph` is the live graph key, and `bpgraph_staging` is where a build writes. **Never write to `bpgraph` outside a build swap.** Experiment in a throwaway graph named `_probe` and delete it afterwards. Connection settings come from `.env`, which is gitignored. `.env.example` documents the variables.

[`graph/docs/schema.md`](graph/docs/schema.md) is the schema contract. FalkorDB is schemaless, so that document is the only thing keeping the graph coherent. [`graph/docs/roadmap.md`](graph/docs/roadmap.md) is where it is going: build today's work so it scales to many host species.

## Read according to the task

- **Building a graph** or changing what it holds: [`graph/docs/build.md`](graph/docs/build.md) and [`graph/docs/export.md`](graph/docs/export.md).
- **Writing the graph's code**, the build, a query API endpoint or the MCP server: [`graph/docs/development.md`](graph/docs/development.md).
- **Writing the client**, a skill or a `bpgraph-client` subcommand: [`client/docs/development.md`](client/docs/development.md).

## Python

`uv` is the package manager and Python is 3.14. Use `uv add` / `uv sync` / `uv run`, never bare `pip` or `python`; `uv add --package bpgraph` or `--package bpgraph-client` adds a dependency to one package.

Type everything — parameters, returns, attributes, record fields — and keep annotations precise rather than convenient: a literal or an enum over a bare `str`, a concrete collection type over `Any`.

`None` and `Optional` are statements about the domain, not escape hatches. Use them only where absence is genuinely possible in the data, never to satisfy the type checker, silence an error, or stand in for a value that is not initialized yet. An awkward type usually means the shape of the code is wrong.

At the end of every coding session, in order, fixing what they surface rather than working around it:

1. Delete dead code, and imports the change introduced or left orphaned.
2. `uv run ruff format .`
3. `uv run ruff check --fix .`
4. `uv run pyright`
5. `uv run python -m compileall -q graph/src client/src`
6. `uv run pytest`
7. `uv run mdformat --wrap no --number *.md graph/docs graph/curation client`

## Git

Do not commit unless the current message asks for it.
