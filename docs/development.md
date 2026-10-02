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
  shape.py      the graph's labels, properties and relationships, as data
  audit.py      check a built graph against docs/schema.md and shape.py
  write/        the write statements, one module per area
  api/          the query API, bpgraph-api: endpoints.py lists them,
                raw.py the schema and Cypher, sequences.py the vaults,
                base.py what they share, names.py checks ids, text.py
                renders results, app.py serves
  guide/        what consumers read: server.md, the MCP server's
                instructions; schema.md, what the `schema` tool returns
  loaders/      a run's files -> the files the graph is written from, checked:
                export.py reads the export, curated.py our rows, host.py the
                IntAct merge, viral.py the viral proteins, peptides.py, and
                run.py puts them together; tsv.py parses, records.py the
                intermediate records
client/         what consumers of the graph need, copied into consulting repos:
  instructions.md
                how a consulting repo's agent works; becomes its AGENTS.md
  skills/       the analysis skills, each self-contained with its scripts;
                .agents/skills and .claude/skills link here
```

`write/` is the only code that decides what is written: every write statement lives there, and `client.py` only runs them. `loaders/` turn a run's files into checked, distinct rows in the run's `build/`; they never touch the database. Keeping that line intact is what stops source quirks reaching the graph.

**Stream everything.** No code, fetch or build, holds a whole file or table in memory: read a line at a time, and where two files meet, key both, sort them on disk and read them side by side with `bpgraph.files`. What may be held whole is reference data of fixed size — PSI-MI, the curated lists — never something that grows with the data. A fetch keeps only what the build reads.

A change to what the graph holds updates [`schema.md`](schema.md) in the same change, along with the writers and `audit.py`. Never let them drift.

**A key that joins several values is a composite key, and every value it joins is a property.** An entity holds every part of its key as its own properties: a viral protein is `NS5A` of virus `3052230`, a name meaningless without its taxon, so it is keyed by `ncbi_taxon_id` and `name`, both properties of `:Viral`, never by an id `<taxon_id>:<name>` joining them. A node that links others — an interaction, a description, an annotation — is identified by what it links, and by its own properties where they change what it states: the keys of the nodes it points to are parts of its key and are not repeated on it. A detail about a fact, such as how it was shown or who recorded it, is not part of its key. A value present only inside an id string is a missing column, so no id is built by joining values: callers name a node by its key's values. A natural key is a single value, such as a peptide's `sequence` or a publication's `pmid`: it is the property itself, and nothing is repeated.

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

Consumers see the MCP server only, and it reaches nothing itself: each of its tools forwards to the query API, which alone reads the graph and the published vaults. An endpoint is a typed function in `src/bpgraph/api/`, taking the `Backend` then its parameters, returning `Record` rows; listing it in `endpoints.py` serves it at `POST /<name>` and makes it a tool of the same name, signature and docstring. Its callers are agents of the first rank: the API answers exactly what they ask and never rewrites, cuts or second-guesses a question. So:

- **The graph is queried as a graph.** `schema` and `cypher` are how an agent reads it: one pattern from the question to the answer, through as many hops as it takes. An endpoint wrapping a graph query would slice the graph into relational steps, and the tool list teaches agents how to reach the data, so it would teach them to chain calls instead of writing patterns. A tool exists only for what Cypher cannot reach, the vaults. When reading something right depends on a convention, such as which side of an interaction a peptide comes from, the model is fixed so a plain pattern reads it, rather than a tool hiding the convention.
- **The signature is the contract.** Annotate every parameter with a `Field` description, and write the docstring for an agent: what comes back, and what to call next.
- **Every token an agent reads is one it cannot spend exploring.** A result is text, rendered by `text.py`: a list is a table, a line counting its rows, a header and one tab-separated line per row, without the columns no row fills. The MCP server sends parameter schemas without titles or null branches, and declares no structured output, so a result reaches the agent once.
- **An unknown id given to a vault tool is an error**, never an empty answer that reads as an absence, checked with `names.py`.
- **Size is the caller's call.** Serving adds `max_tokens` to every endpoint, 25,000 by default, estimated at three characters of text per token: a larger result is refused with its size, its rows and its total, never cut. `cypher` runs as written, under the same rule.
- **What every query needs travels with the server.** Its instructions, `guide/server.md`, reach every agent, subagents included, but Claude Code keeps only their first 2,048 characters: the essentials, first. What interpreting one tool's result takes goes in that tool's description. `schema` returns `guide/schema.md`, the graph as a client needs it, then the Cypher rules, so an agent reads them only when it is about to write Cypher. It is written for clients by hand, not derived from `docs/schema.md`, the builder's contract: a client needs less, and in its own terms. Change it when a change to the graph changes what a client sees.
- **Three levels, each fact once.** The server, its instructions, tool descriptions and `schema`, serves any team: facts about the graph and its tools, never a team's convention such as what counts as golden. `client/instructions.md` holds our team's rules for every query, such as the golden dataset and exploring with subagents. A skill is the recipe for one analysis, with its own report. Nothing a level above already says is repeated below it.
- **Vaults answer through fixed lookups**, by protein or by description; there is no SQL endpoint.
- **Enter through a natural key, then close with `WITH`**: `MATCH (p:Human) WHERE p.accession IN $accessions WITH p MATCH (p)-…`. A filtered `MATCH` is closed with `WITH` before the next one extends it, and a `WITH … WHERE` carries every variable its `WHERE` reads: FalkorDB 6.0.0 dropped a filter that a following `MATCH` extended, and 4.22 refuses a `WHERE` on a variable its `WITH` left behind.
- **Check what `schema.md` teaches on the live graph**: every pattern and rule it gives runs, and answers in well under a second.

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
7. `uv run mdformat --wrap no --number *.md docs curation client`
