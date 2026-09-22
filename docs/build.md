# bpgraph — build and validation

The graph is rebuilt, never updated. Curation happens in the relational
database; a run exports it in full and builds a fresh graph. See
[`schema.md`](schema.md) for what is written.

```
1. index       ->  bpgraph_staging          indexes only, before any data
2. build       ->  bpgraph_staging          CREATE in bulk
3. constrain   ->  bpgraph_staging          unique constraints
4. validate    ->  CALL db.constraints()    every row must be OPERATIONAL
5. swap        ->  RENAME bpgraph_staging bpgraph
```

Indexes come **first** so that every `MATCH` a load performs — and each
relationship write is a key lookup — is index-backed. Constraints come
**last**, because that is what makes them a gate rather than a write-time cost.
A range index may precede its constraint; the reverse is an error, since
creating a unique constraint also creates the index it needs.

`bpgraph.build.build()` runs all five.

`RENAME` overwrites its destination, so step 5 is the whole deployment. Old
graphs are not kept. Staging exists so a bad export cannot land on the live
graph — not for uptime.

## Stages within step 2

1. **Proteins, taxonomy, protein sets** — the entity backbone.
2. **Interactions** — `:Interaction`, `:Description`, `:Publication`,
   `:Method`, `:Peptide`.
3. **Enrichment** — `function` text, `:GoTerm` nodes with the GO ancestor
   closure, and the annotations onto human proteins.
4. **Derive** — the `:Interaction` counters, and the optional
   `:INTERACTS_WITH` shortcut.

A run may skip stage 3. It may not skip stage 4, nor steps 2–5 above.

Stage 3 is fetched beforehand rather than run here, by two commands that write
into `data/` and never touch the graph:

```sh
uv run bpgraph-functions data/graph-2026-09-09   # functions-2026-09-09.tsv
uv run bpgraph-go data/graph-2026-09-09          # go_{terms,edges,annotations}-2026-09-09.tsv
```

The loader reads them from `data/` — not from the export directory, which holds
only what the relational database exports. Each file is named after the
directory it was fetched for, so a new export looks for ones that do not exist
yet instead of reading the last export's. Without them a run builds proteins
with an empty `function` and no `:GoTerm` at all, and says so in the log. The
GO files are written together and read together: some of the three without the
others is an error rather than a partial load.

## Writing

Nothing pre-exists in a fresh graph, so `MERGE` buys nothing and costs a lookup
per row. Deduplicate in Python — the export is a full snapshot, so every
distinct protein, publication, method and peptide is known before the first
write — then write in batches.

```cypher
UNWIND $rows AS r
CREATE (:Protein:Human {id: r.id, accession: r.accession,
                        start: r.start, stop: r.stop, name: r.name,
                        description: r.description, function: r.function,
                        taxon_id: r.taxon_id, taxon_name: r.taxon_name})
```

`GraphWriter.create` writes that clause itself, from the keys of the rows it is
given, so a node's properties and the record behind them are one list rather
than two that can drift.

Nodes first, then relationships by key lookup:

```cypher
UNWIND $rows AS r
MATCH (a:Protein {id: r.a}), (b:Protein {id: r.b})
CREATE (a)<-[:INVOLVES {side: 'a'}]-(:Interaction:VH {id: r.id})-[:INVOLVES {side: 'b'}]->(b)
```

Never interpolate values into Cypher — pass parameters.

## Constraints are the validation gate

Creating a unique constraint over rows that already violate it does not error.
The constraint ends up in state `FAILED`, which `CALL db.constraints()`
reports:

```
type    label    properties  entitytype  status
UNIQUE  Protein  [id]        NODE        FAILED
```

Step 4 is therefore a hard gate: `FAILED` means the export violated a key, and
the staging graph is dropped rather than swapped in. This is what the `id` and
`(accession, start, stop)` constraints are for.

**Wait it out first.** A constraint is applied asynchronously, and reports
`PENDING` and then `UNDER CONSTRUCTION` while it scans — on a graph this size,
for several seconds. Neither is a verdict, and reading one as a failure fails a
sound export; `validate_constraints` polls until every row has settled on
`OPERATIONAL` or `FAILED`.

The gate covers what deduplication cannot see. `bpgraph.dedupe` collapses
records that repeat identically and raises `ConflictingRecords` when two share
a key and disagree, and the loader rejects an accession given as human on one
row and viral on another — but those two mentions have different ids, so
anything the loader misses lands on the composite constraint instead.

## Counters

`Interaction.n_descriptions` / `n_publications` / `n_methods` / `n_peptides`
are computed in one pass at the end of the build, not maintained.

## Auditing what was built

The constraint gate proves keys are unique and nothing else, so `uv run
bpgraph-audit` reads the live graph and checks it against every other promise
in [`schema.md`](schema.md): properties present and correctly typed, no
property the schema does not list, one of `:Human`/`:Viral` and one of
`:HH`/`:VH`, derived ids agreeing with the values behind them, every edge
joining the labels it is declared to join, slot `a` holding the human protein,
the counters equalling what they count, no publication or peptide left with
nothing pointing at it. Each check is one read-only query returning the rows
that break its rule, so an empty result is a pass; the command exits non-zero
when anything fails and prints a few offenders per failure.

Run it after a build, and after anything that touches the writers. It takes
about as long as a build.

`bpgraph.audit` restates those rules by hand rather than deriving them from the
models or the writers — code checked against itself always agrees. Changing the
schema means changing `schema.md`, the writers, **and** the audit, and the
audit failing is what tells you one of the three was missed.
