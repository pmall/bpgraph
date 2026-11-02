# bpgraph — building a graph

The graph is rebuilt, never updated. A run gathers every source into one directory — the curation database's export, and what is fetched for each silo — and builds a fresh graph and fresh vaults from it. [`schema.md`](schema.md) is what is written, and [`roadmap.md`](roadmap.md#principles) says why the sources are split into silos.

## A run

A run is one directory under `data/`, gitignored, named after the export it builds from: `data/2026-09-09/`. What the curation database exports goes in its `export/`, exactly as produced, in the format `bpgraph.loaders.export` gives. The fetch commands fill the rest, each from one public source, and `bpgraph-build` builds it: `uv run bpgraph-build --help` gives their order, and each command's `--help` says what it reads and writes. `bpgraph.run` says where each file of a run lives.

## Staging and the swap <a id="swap"></a>

The live graph `bpgraph` is written by a build's swap and nothing else. A build writes `bpgraph_staging`, checks it, and renames it over `bpgraph`. Staging exists so that a bad export cannot land on the live graph, not for uptime: old graphs are not kept, and a build that fails leaves the live graph as it was.

## Auditing

A build's constraint gate proves that the natural keys are unique, and nothing else. Run `bpgraph-audit` after every build, and after anything that touches the writers: it checks the live graph against every [invariant](schema.md#invariants) of the schema, as `bpgraph.audit` says.
