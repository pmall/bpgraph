# bpgraph-client

The package `bpgraph-client`: what a repository consulting bpgraph needs, maintained beside the graph it queries. It reaches the graph through the MCP server's tools only, and never imports `bpgraph`.

## Folders

- `instructions.md`, the rules its agent works by, which become the consulting repository's `AGENTS.md`.
- `skills/`, the analyses that recur, each a skill with its standard queries; `.agents/skills` and `.claude/skills` link here.
- `src/bpgraph_client/`, the `bpgraph-client` command; `tests/`, its tests.
- `docs/`, [`development.md`](docs/development.md): how the client is written, and how a [consulting repository](docs/development.md#consulting-repository) installs it.

## Commands

`bpgraph-client` does the mechanical part of the skills, on what they gathered from the graph, so that the same input always gives the same output; it never reaches the graph itself. `bpgraph-client --help` lists its commands, and each one's `--help` says what it does.
