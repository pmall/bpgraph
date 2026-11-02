# bpgraph — agent guide

A FalkorDB knowledge graph of protein–protein interactions, human–human and virus–human, rich in text: every interaction is backed by the publications that report it, titles and abstracts included, and proteins carry their UniProt function text and experimental GO annotations of what they do, each tied to its publications. A viral protein is a curated one, `HBx` of HBV, pooled over the strains and accessions it was observed on. Scripts do the deterministic work. The agent is the explorer: it reads that connected text and makes the connections a person would need years of reading to make.

This repository builds the graph and serves it. It does not explore it: consulting repositories do, through the MCP server alone.

## Where things are

The repository is a uv workspace of two packages, each standing alone with its code, docs and processes; the root only runs their tools together, and its `README.md` presents the project. The graph is made for any team and is unaware of our client: nothing in `graph/` imports or names a concept of `client/` (its instructions, its skills, the golden dataset). The client is made for the graph and uses what the MCP server says freely, but never imports `bpgraph`: it reaches the graph only through the MCP server's tools. A ruff rule bans the import both ways.

- `graph/`: the graph and everything around it, the package `bpgraph` and its `bpgraph-*` commands: `graph/src/bpgraph/`, the build, the query API and the MCP server; `graph/tests/`, its tests, the docs against the code; `graph/curation/`, the curated lists a build reads; `graph/docs/`, the builder's docs; `graph/README.md`, the package and its folders; `graph/Dockerfile`, the image of the query API and the MCP server. What any team's queries need travels with the MCP server, never one team's conventions, so every agent gets it without reading a file: its instructions, `graph/src/bpgraph/guide/server.md`, kept under the 2,048 characters Claude Code passes on; the tool descriptions; and the `schema` tool, which returns `graph/src/bpgraph/guide/schema.md`: the graph as a client sees it, written for clients and kept apart from the builder's contract, `graph/docs/schema.md`.
- `client/`: what a repository consulting the graph needs, the package `bpgraph-client`: `client/instructions.md`, which becomes the consulting repository's `AGENTS.md` and holds our rules for every query, the golden dataset, deterministic work in one agent and exploration fanned out to subagents; `client/skills/`, the analyses that recur, which `.agents/skills` and `.claude/skills` link to; `client/src/bpgraph_client/`, the `bpgraph-client` command, the mechanical part of the skills; `client/tests/`, its tests; `client/README.md`, the package and its folders; `client/docs/development.md`, how it is written and how a consulting repository installs it. A skill says what to analyse and what to report, and a `bpgraph-client` subcommand gives it a standard entry point for the mechanical part.
- The root: the workspace, `pyproject.toml` and `uv.lock`; `docker-compose.yml` and `.env`, which run the services; `_data/`, the runs a build reads and the vaults of the live graph, gitignored.

## The graph is the source of truth

The live graph `bpgraph` on the FalkorDB server is the only source of truth about the data. `_data/` holds the sources a build ingests, not answers.

`docker compose up -d` brings up:

| service            | port | role                                                    |
| ------------------ | ---- | ------------------------------------------------------- |
| `falkordb-server`  | 6379 | the graph                                               |
| `falkordb-browser` | 3000 | UI. Log in with host `falkordb-server`, not `localhost` |
| `bpgraph-api`      | —    | query API, internal: schema, Cypher, vault lookups      |
| `bpgraph-mcp`      | 8080 | MCP at `/mcp`: the API's endpoints as tools, read-only  |

`bpgraph` is the live graph key, and `bpgraph_staging` is where a build writes. **Never write to `bpgraph` outside a [build swap](graph/docs/build.md#swap).** Experiment in a throwaway graph named `_probe` and delete it afterwards. Connection settings come from `.env`, which is gitignored. `.env.example` documents the variables.

[`graph/docs/schema.md`](graph/docs/schema.md) is the schema contract. FalkorDB is schemaless, so that document is the only thing keeping the graph coherent. [`graph/docs/roadmap.md`](graph/docs/roadmap.md) is where it is going: build today's work so it scales to many host species.

## Read according to the task

- **Building a graph** or changing what it holds: [`graph/docs/build.md`](graph/docs/build.md), and the export's format in `graph/src/bpgraph/loaders/export.py`.
- **Writing the graph's code**, the build, a query API endpoint or the MCP server: [`graph/docs/development.md`](graph/docs/development.md).
- **Writing the client**, a skill or a `bpgraph-client` subcommand: [`client/docs/development.md`](client/docs/development.md).
- **Writing a doc, a docstring, a README or a prompt**: [the rules for docs](#docs).

## Docs <a id="docs"></a>

- The reference docs are explanations, instructions and rules for the working agent, timeless and right at reading time: they describe the current rules and the current state. Every paragraph is something the agent needs to act correctly now. No account of how things came to be (what changed, was added or removed, and when), no detail a tool or a check already enforces, no dates, no counts, no results of a run, no status tags, no plans: the plans and their status are `graph/docs/roadmap.md`'s alone. Every rule written is decided.
- The docs of each package hold its rules, each written once, in its place; other docs point to it, a client doc to a graph doc, never the reverse. Each doc keeps to its scope: `schema.md` the graph, its keys and its invariants, `build.md` how a graph is built and published, `development.md` how the graph's code is written, `roadmap.md` where the graph is going, `graph/curation/*.md` what a curated list means, `client/docs/development.md` how the client is written and installed.
- Every fact is written in one place, and everything else points to it: the code in its docstrings (a command, with the formats of the files it reads and writes, in the docstring of its module, which its `--help` prints, `argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)`; an MCP tool in its endpoint's docstring, the description the server sends; a function in its own), a rule in its doc, a process in the skill or prompt that runs it, or in the doc of its scope where none does. The READMEs, the repository's and each package's, present them to people: a projection of their content at a level that only a big refactoring of their functionality changes (what each part is for, how the parts fit, how to run it), pointing to the details, never listing what changes with the code (its commands, tools, options, formats, rules). Only the prompts repeat, condensed, what they need; a fact that rarely moves, such as an invariant, may also be restated where its reader needs it, a tool never.
- Everything is referenced by a stable ID, never by its number or its wording: a section by the ID its heading ends with, `<a id="<id>"></a>`, given when it is first referenced and never changed (`graph/docs/schema.md#keys`, `#keys` in its own file); an invariant by its ID (`D5`), and a roadmap step by its own (`second-host`). Headings are not numbered; a numbered list gives an order, and nothing points to an item by its number.
- The prompts hold the processes, each self-contained: the skills and `client/instructions.md`, and what the MCP server sends, `guide/server.md`, `guide/schema.md` and the tool descriptions. Each holds the whole process it runs, the formats it writes and the tools it uses, condensed, so that an agent spends its context on its job, not on reading docs. It reads no doc; it repeats of a doc or a docstring only the short parts it needs (the fields of a file, a query's parameters), and relies on the description the server sends of a tool it uses, repeating only how the tool fits its process. Two prompts may give the same instruction.
- Keep the docs and the prompts up to date with every decision: a change of a format or a tool updates its docstring and the prompts that repeat it.

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
7. `uv run mdformat --wrap no --number *.md graph/*.md graph/docs graph/curation graph/src/bpgraph/guide client`

## Git

Do not commit unless the current message asks for it.
