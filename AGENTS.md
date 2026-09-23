# bpgraph — agent guide

A FalkorDB knowledge graph of protein–protein interactions, human–human and virus–human, enriched with UniProt descriptions, GO annotations on the human proteins, NCBI taxonomy, and the publications and detection methods behind every interaction. Claude queries it through a read-only MCP server to run interactome analyses — typically: take a topic curated as a list of human proteins (e.g. ferroptosis) and compare how viral families act on it.

Curation happens in a separate relational database. A run exports it as TSV files into `data/<date>/export/` — gitignored — fetches what the export lacks beside it, and builds a fresh graph; the graph is never edited in place.

## Documents

**[`docs/schema.md`](docs/schema.md) is the schema contract.** FalkorDB is schemaless, so that document is the only thing keeping the graph coherent. Read it before writing any Cypher, any Pydantic model, or any loader, and update it in the same change that changes the graph — never let the two drift.

Read these when the task reaches them, not before:

- [`docs/export.md`](docs/export.md) — the TSV files a run ingests, and their columns.
- [`docs/build.md`](docs/build.md) — how a run builds, validates and swaps a graph, and how to audit the result.
- [`docs/queries.md`](docs/queries.md) — canonical queries and a worked example.
- [`docs/mcp-client.md`](docs/mcp-client.md) — the schema digest handed to MCP clients. Update it with `docs/schema.md`.

## Layout

```
data/           one directory per run: export/ as the database wrote it,
                the taxonomy, function text and GO fetched for it, and
                topics/ resolved against it. Gitignored
src/bpgraph/
  config.py     env-driven connection settings
  client.py     thin FalkorDB wrapper: parameterized query/write
  ids.py        the two derived ids — nothing else may build one
  run.py        where a run directory keeps each file
  enums.py      closed vocabularies shared by models, ids and writers
  models.py     Pydantic models mirroring docs/schema.md
  dedupe.py     collapse repeated records, and reject ones that disagree
  taxonomy.py   the NCBI dump in SQLite; cuts the taxa the graph keeps
  uniprot.py    fetches the function text into a run directory
  go.py         cuts GO down to what an export reaches, likewise
  schema.py     index and constraint DDL, and the validation gate
  build.py      run a full build: stages, validation gate, swap
  audit.py      check a built graph against docs/schema.md
  api/          batched writers, one module per area
  loaders/      tsv.py: the export parser -> Pydantic models
```

`api/` is the only code that writes Cypher. `loaders/` parse sources into Pydantic models and hand them to `api/`; they never touch the database. Keeping that line intact is what stops source quirks reaching the graph.

## FalkorDB

`docker compose up -d` brings up three containers:

| service            | port | role                                                    |
| ------------------ | ---- | ------------------------------------------------------- |
| `falkordb-server`  | 6379 | the graph. Builds write here                            |
| `falkordb-browser` | 3000 | UI. Log in with host `falkordb-server`, not `localhost` |
| `falkordb-mcp`     | 8080 | MCP at `/mcp`, **read-only by design**                  |

`bpgraph` is the live graph key and `bpgraph_staging` is where a run builds; old versions are not kept. Builds go over RESP on 6379, MCP clients only query — do not add write paths through MCP. Connection settings come from `.env`, which is gitignored; `.env.example` documents the variables.

**Never write to `bpgraph` outside a build swap.** Experiment in a throwaway graph named `_probe` and delete it afterwards.

**Check the running image rather than the documentation.** FalkorDB's published docs lag its releases, so before asserting what the engine supports — index kinds, constraint syntax, procedure names, Cypher coverage — probe it:

```sh
docker exec bpgraph-falkordb-server-1 redis-cli MODULE LIST
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.QUERY _probe "CALL dbms.procedures() YIELD name RETURN name"
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.DELETE _probe
```

## Writing code

`uv` is the package manager and Python is 3.14. Use `uv add` / `uv sync` / `uv run`, never bare `pip` or `python`.

Type everything — parameters, returns, attributes, Pydantic fields — and keep annotations precise rather than convenient: a literal or an enum over a bare `str`, a concrete collection type over `Any`.

`None` and `Optional` are statements about the domain, not escape hatches. Use them only where absence is genuinely possible in the data, never to satisfy the type checker, silence an error, or stand in for a value that is not initialized yet. An awkward type usually means the shape of the code is wrong. The graph follows the same rule: no property in `docs/schema.md` is optional, and unknown free text is `''`.

## Verification

At the end of every coding session, in order, fixing what they surface rather than working around it:

1. Delete dead code, and imports the change introduced or left orphaned.
2. `uv run ruff format .`
3. `uv run ruff check --fix .`
4. `uv run pyright`
5. `uv run python -m compileall -q src` — add other code roots as they appear.
6. `uv run pytest`, if there is anything to test. This is ingestion code and query scripts; most of it is verified by running it, not by unit tests.
7. `uv run mdformat --wrap no --number *.md docs`

## Topics

A topic reaches us as a biologist's spreadsheet, and no two are alike: different columns, symbols with aliases in the cell, genes encoding several proteins. There is no parser for them. Resolve each list by judgment into `data/<run>/topics/<topic>.tsv` — `accession` and whatever the topic records — asking about anything ambiguous, and document its columns in `docs/schema.md` and `TOPIC_PROPERTIES` in `audit.py`. Resolve again for every new export. See [`docs/export.md`](docs/export.md).

## Git

Do not commit unless the current message asks for it. No co-authors.
