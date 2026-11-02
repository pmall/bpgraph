# bpgraph — development

Conventions for changing the graph's code: the build, the query API and the MCP server. The workspace's Python rules and verification are in the root `AGENTS.md`. [`README.md`](../README.md) says what each folder holds, and each module what it does, in its docstring.

## The code <a id="code"></a>

`write/` is the only code that decides what is written: every write statement lives there, and `client.py` only runs them. `loaders/` turn a run's files into checked, distinct rows in the run's `build/`; they never touch the database. Keeping that line intact is what stops source quirks reaching the graph.

**Stream everything.** No code, fetch or build, holds a whole file or table in memory: read a line at a time, and where two files meet, key both, sort them on disk and read them side by side with `bpgraph.files`. What may be held whole is reference data of fixed size — PSI-MI, the curated lists — never something that grows with the data. A fetch keeps only what the build reads.

A change to what the graph holds updates [`schema.md`](schema.md) in the same change, along with the writers, `shape.py` and `audit.py`, and `guide/schema.md` when a client sees it. Never let them drift: `uv run pytest` checks both schemas against `shape.py`, and the [invariants](schema.md#invariants) against the audit's checks. Nodes are keyed as the schema's [principles](schema.md#principles) say.

## FalkorDB <a id="falkordb"></a>

**The engine is pinned**, `falkordb/falkordb-server:v4.22.0` in `docker-compose.yml`: the C engine. `latest` is not safe to follow: it can point at a release such as 6.0.0, the first of a Rust rewrite, whose planner drops the `WHERE` of a `MATCH` that a following `MATCH` extends — `MATCH (i:VH) WHERE i.n_publications >= 2 MATCH (i)-[:INVOLVES]->(h)` counts every VH. A change of version is a rebuild: never rely on one engine reading what another wrote.

To try a version, 6.x included: pin it, restart, rebuild, then run `bpgraph-audit`, whose check `E1`, that the engine keeps the `WHERE` of a `MATCH` that a following `MATCH` extends, fails on an engine that drops filters, and time the audit and the query API's endpoints against the last version. Keep the pin if any of it regresses.

What 4.22 does that the queries work around:

- **`outdegree(n, 'TYPE')` costs more the more edges of that type the graph holds**: instant on `OF_TERM`, never ending on `SUPPORTS`, which has an edge per description. Count instead: the edges, the distinct sources and the nodes.
- **A bare `RETURN count(r)` over one edge type is answered from a tally**, instantly; behind a `WITH` it scans every node. Bind the edge and count it: `MATCH ()-[:INVOLVES]->() RETURN count(*)` counts one row per pair of nodes, so a homodimer's two edges count once.
- **Enter through a natural key, then close with `WITH`**: `MATCH (p:Human) WHERE p.accession IN $accessions WITH p MATCH (p)-…`. A filtered `MATCH` is closed with `WITH` before the next one extends it, and a `WITH … WHERE` carries every variable its `WHERE` reads: FalkorDB 6.0.0 drops a filter that a following `MATCH` extends, and 4.22 refuses a `WHERE` on a variable its `WITH` left behind.

**Check the running image rather than the documentation.** FalkorDB's published docs lag its releases, so before asserting what the engine supports — index kinds, constraint syntax, procedure names, Cypher coverage — probe it:

```sh
docker exec bpgraph-falkordb-server-1 redis-cli MODULE LIST
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.QUERY _probe "CALL dbms.procedures() YIELD name RETURN name"
docker exec bpgraph-falkordb-server-1 redis-cli GRAPH.DELETE _probe
```

## The query API and the MCP server <a id="query-api"></a>

Consumers see the MCP server only, and it reaches nothing itself: each of its tools forwards to the query API, which alone reads the graph and the published vaults. `bpgraph.api` says how an endpoint is written and served, and `bpgraph.server` how it becomes a tool. Its callers are agents of the first rank: the API answers exactly what they ask and never rewrites, cuts or second-guesses a question. So:

- **The graph is queried as a graph.** `schema` and `cypher` are how an agent reads it: one pattern from the question to the answer, through as many hops as it takes. An endpoint wrapping a graph query would slice the graph into relational steps, and the tool list teaches agents how to reach the data, so it would teach them to chain calls instead of writing patterns. A tool exists only for what Cypher cannot reach, the vaults. When reading something right depends on a convention, such as which side of an interaction a peptide comes from, the model is fixed so a plain pattern reads it, rather than a tool hiding the convention.
- **The signature is the contract.** Annotate every parameter with a `Field` description, and write the docstring for an agent: what comes back, and what to call next. It is the tool's description, and no doc repeats it.
- **Every token an agent reads is one it cannot spend exploring.** A result is text, a table where it is a list, as `bpgraph.api.text` renders it, and a tool's parameter schema is lean, as `bpgraph.server` sends it.
- **An unknown id given to a vault tool is an error**, never an empty answer that reads as an absence, checked with `names.py`.
- **Size is the caller's call.** A result over the caller's `max_tokens` is refused with its size, never cut, as `bpgraph.api.endpoints` says. `cypher` runs as written, under the same rule.
- **What every query needs travels with the server.** Its instructions, `guide/server.md`, reach every agent, subagents included, but Claude Code keeps only their first 2,048 characters: the essentials, first. What interpreting one tool's result takes goes in that tool's description. `schema` returns `guide/schema.md`, the graph as a client needs it, then the Cypher rules, so an agent reads them only when it is about to write Cypher. It is written for clients by hand, not derived from `docs/schema.md`, the builder's contract: a client needs less, and in its own terms. Change it when a change to the graph changes what a client sees.
- **Three levels, each fact once.** The server, its instructions, tool descriptions and `schema`, serves any team: facts about the graph and its tools, never a team's convention such as what counts as golden. A team's rules for every query, and the recipes of its analyses, live with its client. Nothing the server already says is repeated there.
- **Vaults answer through fixed lookups**, by protein or by description; there is no SQL endpoint.
- **Check what `guide/schema.md` teaches on the live graph**: every pattern and rule it gives runs, and answers in well under a second.

Both run in Docker from one image, so a change to `src/` reaches them only once rebuilt: `docker compose up -d --build bpgraph-api bpgraph-mcp`. To serve from the working tree instead, stop the containers and run `uv run bpgraph-api` and `uv run bpgraph-mcp`.

## Writing code

The graph follows the root `AGENTS.md`'s rule on `None`: no property in `schema.md` is optional, and unknown free text is `''`. Most of the graph's code is ingestion and query code, verified by running it rather than by unit tests; the tests check what needs no graph, the docs against the code.
