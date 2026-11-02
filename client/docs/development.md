# bpgraph-client — development

The client is what a repository consulting bpgraph needs, maintained here beside the graph it queries. It never imports `bpgraph`: it reaches the graph through the MCP server's tools only, and knows of it only what the server says.

## Layout

```
instructions.md   how a consulting repository's agent works; becomes its AGENTS.md
skills/           the analysis skills; .agents/skills and .claude/skills link here
src/bpgraph_client/
  __init__.py     the bpgraph-client command, one subcommand per module
  render.py       render: a network.json drawn as a page, from cytoscape.html
tests/            the commands' tests
```

## Two levels below the server

The MCP server says what any team needs to query the graph: its instructions, its tools' descriptions and `schema`. `instructions.md` holds our team's rules for every query, such as the golden dataset and exploring with subagents. A skill is the recipe for one analysis, with its own report. Nothing a level above already says is repeated below it.

## Skills and commands

A skill says what to analyse and what to report. It queries the graph through the MCP tools; a standard query sits in its `queries/` folder and runs with `cypher` as written, so its runs compare. The mechanical part, done on what the skill gathered, is a `bpgraph-client` subcommand: a module of `bpgraph_client`, described in its docstring and listed in `COMMANDS`. A command never reaches the graph.

## A consulting repository

It depends on this package, and copies the instructions and the skills from the same commit:

```sh
uv add "git+ssh://git@github.com/pmall/bpgraph.git#subdirectory=client"
```

`instructions.md` becomes its `AGENTS.md`, `skills/` its `.claude/skills` and `.agents/skills`, and it registers the MCP server, `http://<host>:8080/mcp`. A skill and the command it runs change together, so the skills are copied again whenever the package is upgraded.
