# bpgraph — development

Conventions for changing the code, whether the build or a skill's script.

## Layout

```
data/           one directory per run: export/ as the database wrote it,
                the taxonomy, function text and GO fetched for it, and
                topics/ resolved against it. Gitignored
curation/       viruses.tsv, the curated viruses; viruses.md, why;
                methods.tsv, the method classes; methods.md, why
src/bpgraph/
  config.py     env-driven connection settings
  client.py     thin FalkorDB wrapper: parameterized query/write
  query.py      read-only Cypher on the live graph, and bpgraph-query
  server.py     the MCP server, bpgraph-mcp: tools over query.py
  ids.py        the derived ids — nothing else may build one
  run.py        where a run directory keeps each file
  sources.py    which release of each dataset a run was fetched from
  enums.py      closed vocabularies shared by models, ids and writers
  models.py     Pydantic models mirroring docs/schema.md
  dedupe.py     collapse repeated records, and reject ones that disagree
  taxonomy.py   the NCBI dump in SQLite, bpgraph-taxonomy; families
  viruses.py    curation/viruses.tsv, and placing a taxon under its virus
  uniprot.py    fetches the function text into a run directory
  go.py         cuts GO down to what an export reaches, likewise
  schema.py     index and constraint DDL, and the validation gate
  build.py      run a full build: stages, validation gate, swap
  audit.py      check a built graph against docs/schema.md
  network.py    draw a network: network.json in, a standard page out
  templates/    the network renderers, one HTML file each
  api/          batched writers, one module per area
  loaders/      tsv.py: the export parser -> Pydantic models
.agents/skills/ the analysis skills; .claude/skills links to them
```

`api/` is the only code that decides what is written: every write statement lives there, and `client.py` only runs them. `loaders/` parse sources into Pydantic models and hand them to `api/`; they never touch the database. Keeping that line intact is what stops source quirks reaching the graph.

A change to what the graph holds updates [`schema.md`](schema.md) in the same change, along with the writers and `audit.py`. Never let them drift.

## FalkorDB

**Check the running image rather than the documentation.** FalkorDB's published docs lag its releases, so before asserting what the engine supports — index kinds, constraint syntax, procedure names, Cypher coverage — probe it:

```sh
docker exec bpgraph-falkordb-server-1 redis-cli MODULE LIST
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.QUERY _probe "CALL dbms.procedures() YIELD name RETURN name"
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.DELETE _probe
```

## The MCP server

It runs in Docker, built from this repository, so a change to `src/` reaches it only once rebuilt: `docker compose up -d --build bpgraph-mcp`. Run `uv run bpgraph-mcp` to serve from the working tree instead, after stopping the container. Every tool it offers is read-only.

## Writing code

`uv` is the package manager and Python is 3.14. Use `uv add` / `uv sync` / `uv run`, never bare `pip` or `python`.

Type everything — parameters, returns, attributes, Pydantic fields — and keep annotations precise rather than convenient: a literal or an enum over a bare `str`, a concrete collection type over `Any`.

`None` and `Optional` are statements about the domain, not escape hatches. Use them only where absence is genuinely possible in the data, never to satisfy the type checker, silence an error, or stand in for a value that is not initialized yet. An awkward type usually means the shape of the code is wrong. The graph follows the same rule: no property in `schema.md` is optional, and unknown free text is `''`.

## Verification

At the end of every coding session, in order, fixing what they surface rather than working around it:

1. Delete dead code, and imports the change introduced or left orphaned.
2. `uv run ruff format .`
3. `uv run ruff check --fix .`
4. `uv run pyright`
5. `uv run python -m compileall -q src` — add other code roots as they appear.
6. `uv run pytest`, if there is anything to test. This is ingestion code and query scripts; most of it is verified by running it, not by unit tests.
7. `uv run mdformat --wrap no --number *.md docs curation .agents/skills`
