# bpgraph — development

Conventions for changing the code, whether the build or a skill's script.

## Layout

```
data/           one directory per run: export/ as the database wrote it, what
                every silo shares (taxonomy, PSI-MI), one directory per
                silo (hosts/9606/, viral/), and the vaults the build
                writes; vault/, the vaults of the live graph, which the
                build publishes and the API reads. Gitignored
curation/       viruses.tsv, the curated viruses; viruses.md, why;
                methods.tsv, the IntAct keep flag; methods.md, where it comes from;
                publications.tsv, publications that repeat one experiment;
                publications.md, how IntAct resolves them
src/bpgraph/
  config.py     env-driven connection settings
  client.py     thin FalkorDB wrapper: batched, parameterized writes
  files.py      intermediate files: sorted on disk, read side by side
  query.py      read-only Cypher on the live graph, and bpgraph-query
  server.py     the MCP server, bpgraph-mcp: each API endpoint as a tool
  ids.py        the derived ids — nothing else may build one
  run.py        where a run directory keeps each file, silo by silo
  sources.py    which release of each dataset a run was fetched from
  enums.py      closed vocabularies shared by loaders, ids and writers
  taxonomy.py   the NCBI dump in SQLite, bpgraph-taxonomy; families
  viruses.py    curation/viruses.tsv, and placing a taxon under its virus
  psimi.py      the PSI-MI ontology, bpgraph-psimi
  methods.py    curation/methods.tsv, the IntAct keep flag, bpgraph-methods
  publications.py  curation/publications.tsv, the repeating publication groups
  obo.py        the OBO format GO and PSI-MI share
  swissprot.py  a host's Swiss-Prot and sequences, bpgraph-swissprot
  intact.py     a host's IntAct, filtered, bpgraph-intact
  go.py         a host's experimental, functional GO annotations, bpgraph-go
  uniprot.py    the viral silo's function text and protein names, bpgraph-functions
  pubmed.py     each silo's publication metadata, bpgraph-pubmed
  vault.py      the sequence vaults: writing, publishing, reading one protein
  schema.py     index and constraint DDL, and the validation gate
  build.py      run a full build: prepare, write, gate, swap, vaults
  audit.py      check a built graph against docs/schema.md
  network.py    draw a network: network.json in, a standard page out
  templates/    the network renderers, one HTML file each
  write/        the write statements, one module per area
  api/          the query API, bpgraph-api: endpoints.py lists them, one
                module per area, base.py what they share, app.py serves
  loaders/      a run's files -> the files the graph is written from, checked:
                export.py reads the export, curated.py our rows, host.py the
                IntAct merge, viral.py the viral proteins, peptides.py, and
                run.py puts them together; tsv.py parses, records.py the
                intermediate records
skills/         the analysis skills; .agents/skills and .claude/skills link here
```

`write/` is the only code that decides what is written: every write statement lives there, and `client.py` only runs them. `loaders/` turn a run's files into checked, distinct rows in the run's `build/`; they never touch the database. Keeping that line intact is what stops source quirks reaching the graph.

**Stream everything.** No code, fetch or build, holds a whole file or table in memory: read a line at a time, and where two files meet, key both, sort them on disk and read them side by side with `bpgraph.files`. What may be held whole is reference data of fixed size — PSI-MI, the curated lists — never something that grows with the data. A fetch keeps only what the build reads.

A change to what the graph holds updates [`schema.md`](schema.md) in the same change, along with the writers and `audit.py`. Never let them drift.

## FalkorDB

**The engine is pinned**, `falkordb/falkordb-server:v4.22.0` in `docker-compose.yml`: the C engine, FalkorDB's current release. `latest` is not safe to follow. On 2026-09-29 it moved to 6.0.0, the first release of a Rust rewrite, whose planner dropped the `WHERE` of a `MATCH` that a following `MATCH` extended — `MATCH (i:VH) WHERE i.n_publications >= 2 MATCH (i)-[:INVOLVES]->(h)` counted every VH — and it moved back the next day. A change of version is a rebuild: never rely on one engine reading what another wrote.

To try a version, 6.x included: pin it, restart, rebuild — a rebuild is two and a half minutes — then run `bpgraph-audit`, whose `engine.filters` check fails on an engine that drops filters, and time the audit and the query API's endpoints against the last version. Keep the pin if any of it regresses.

What 4.22 does that the queries work around:

- **`outdegree(n, 'TYPE')` costs more the more edges of that type the graph holds**: instant on `OF_TERM`, never ending over a million descriptions on `SUPPORTS`. Count instead: the edges, the distinct sources and the nodes.
- **A bare `RETURN count(r)` over one edge type is answered from a tally**, instantly; behind a `WITH` it scans every node. Bind the edge and count it: `MATCH ()-[:INVOLVES]->() RETURN count(*)` counts one row per pair of nodes, so a homodimer's two edges count once.
- **Queries time out after 60 s**, `TIMEOUT_DEFAULT`; a client may ask for up to ten minutes, `TIMEOUT_MAX`.
- **Data lives in `/var/lib/falkordb/data`** in this image, where the `falkordb_data` volume is mounted. At `/data`, nothing would survive a restart.

**Check the running image rather than the documentation.** FalkorDB's published docs lag its releases, so before asserting what the engine supports — index kinds, constraint syntax, procedure names, Cypher coverage — probe it:

```sh
docker exec bpgraph-falkordb-server-1 redis-cli MODULE LIST
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.QUERY _probe "CALL dbms.procedures() YIELD name RETURN name"
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.DELETE _probe
```

## The query API and the MCP server

Consumers see the MCP server only, and it reaches nothing itself: each of its tools forwards to the query API, which alone reads the graph and the published vaults. An endpoint is a typed function in `src/bpgraph/api/`, taking the `Backend` then its parameters, returning `Record` rows; listing it in `endpoints.py` serves it at `POST /<name>` and makes it a tool of the same name, signature and docstring. So:

- **The signature is the contract.** Annotate every parameter with a `Field` description, and write the docstring for an agent that has not read the schema: what comes back, which pitfall the query handles for it, what to call next.
- **An endpoint is a question analyses keep asking**, not a query one analysis needed. It stays bounded: a scope parameter it cannot run without, and a `limit`.
- **Vaults answer one protein at a time**, through fixed lookups; there is no SQL endpoint.
- **Enter through an indexed label, then close with `WITH`**: `MATCH (p:Protein) WHERE p.id IN $ids WITH p MATCH (p)-…`. Only `:Protein`, not `:Human` or `:Viral`, has the `id` index. A filtered `MATCH` is closed with `WITH` before the next one extends it, and a `WITH … WHERE` carries every variable its `WHERE` reads: FalkorDB 6.0.0 dropped a filter that a following `MATCH` extended, and 4.22 refuses a `WHERE` on a variable its `WITH` left behind.
- **Check an endpoint against an independent query** before relying on it, and time it on the live graph: every one answers in well under a second.

Both run in Docker from one image, so a change to `src/` reaches them only once rebuilt: `docker compose up -d --build bpgraph-api bpgraph-mcp`. To serve from the working tree instead, stop the containers and run `uv run bpgraph-api` and `uv run bpgraph-mcp`; the MCP server finds the API at `BPGRAPH_API`, `http://127.0.0.1:8000` by default.

## Writing code

`uv` is the package manager and Python is 3.14. Use `uv add` / `uv sync` / `uv run`, never bare `pip` or `python`.

Type everything — parameters, returns, attributes, record fields — and keep annotations precise rather than convenient: a literal or an enum over a bare `str`, a concrete collection type over `Any`.

`None` and `Optional` are statements about the domain, not escape hatches. Use them only where absence is genuinely possible in the data, never to satisfy the type checker, silence an error, or stand in for a value that is not initialized yet. An awkward type usually means the shape of the code is wrong. The graph follows the same rule: no property in `schema.md` is optional, and unknown free text is `''`.

## Verification

At the end of every coding session, in order, fixing what they surface rather than working around it:

1. Delete dead code, and imports the change introduced or left orphaned.
2. `uv run ruff format .`
3. `uv run ruff check --fix .`
4. `uv run pyright`
5. `uv run python -m compileall -q src` — add other code roots as they appear.
6. `uv run pytest`, if there is anything to test. This is ingestion code and query scripts; most of it is verified by running it, not by unit tests.
7. `uv run mdformat --wrap no --number *.md docs curation skills`
