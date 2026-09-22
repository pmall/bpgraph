# bpgraph — export format

What to export from the relational database, as tab-separated files dropped in
a directory under **`data/`**, which is gitignored.
`bpgraph.loaders.tsv.TsvExport` reads one such directory; see
[`schema.md`](schema.md) for what the files become.

Three files carry the whole export. There is no protein table and no method
table: a description row restates its two partners and its detection method
inline, and the build reconciles the repeats.

| file | one row per |
|---|---|
| [`descriptions.tsv`](#descriptionstsv) *(required)* | observation — a pair, a publication, a method |
| [`publications.tsv`](#publicationstsv) *(required)* | publication |
| [`peptides.tsv`](#peptidestsv) | peptide a description reports |

Conventions for every file:

- Tab-separated, UTF-8, one header row. Column order does not matter, names do.
- Leading and trailing whitespace is stripped from every cell.
- Every listed column must be present, and no cell may be empty except where
  the table says so. Empty means the empty string, never `NULL` or `\N`.
- **One line is one row, and quoting is off.** A double quote is ordinary text,
  so abstracts keep theirs — but a cell may hold no tab and no newline of its
  own. Strip both from free text on the way out; a line that does not have the
  expected number of columns is rejected by its line number.

[`docs/example-export/`](example-export) holds a small working example of every
file, and every snippet below is a row from it. Loading that directory builds
the graph [`queries.md`](queries.md) walks through.

**Proteins are referenced by their natural key, never by an id** — the ids are
derived during the build. Which key depends on the file. `descriptions.tsv` and
`peptides.tsv` can name either partner, so they carry `accession`, `start` and
`stop`. `memberships.tsv` and `go_annotations.tsv` apply only to human
proteins, and a human accession identifies exactly one of those, so they carry
`accession` alone.

---

## descriptions.tsv *(required)*

One row per description: one protein pair, one publication, one method. This
is also where proteins and methods come from — the file is read twice, once to
gather them and once to build the descriptions against them.

| column | notes |
|---|---|
| `stable_id` | your identifier. Becomes the node's key, so it must be unique |
| `type` | `hh` or `vh` |
| `pmid` | must appear in `publications.tsv` |
| `psimi_id` | `MI:` followed by four digits |
| `method` | the method's name, e.g. `two hybrid` |
| `accession1`, `start1`, `stop1` | the first partner — always human |
| `name1`, `description1`, `ncbi_taxon_id1` | and how it is described |
| `accession2`, `start2`, `stop2` | the second partner — viral exactly when `type` is `vh` |
| `name2`, `description2`, `ncbi_taxon_id2` | and how it is described |

```
stable_id  type  pmid      psimi_id  method       accession1  start1  stop1  name1  description1           ncbi_taxon_id1  accession2  start2  stop2  name2  description2        ncbi_taxon_id2
D-00417    vh    12345678  MI:0018   two hybrid   P36969      1       197    GPX4   Phospholipid hydrope…  9606            P27958      1973    2419   NS5A   Genome polyprotein  11103
D-00418    vh    12345678  MI:0006   anti bait…   P36969      1       197    GPX4   Phospholipid hydrope…  9606            P27958      1973    2419   NS5A   Genome polyprotein  11103
D-00901    hh    22222222  MI:0006   anti bait…   P36969      1       197    GPX4   Phospholipid hydrope…  9606            O60488      1       711    ACSL4  Long-chain-fatty-a…  9606
```

The first two rows are the same pair by different methods. They become one
`:Interaction` carrying two `:Description` nodes, and its counters record two
descriptions, one publication and two methods — which is what makes the
counters a confidence signal rather than a row count.

**Slot 1 is always the human partner.** Nothing else says which side is viral:
a `vh` row's second partner is the viral one, every other partner is human, and
an accession that appears on both sides of that line is rejected. The build
then puts the human protein on side `a` of the interaction regardless of the
order it was given in.

Two viral proteins may not interact, so there is no `vv`. A pair **may**
interact with itself: a homodimer is an ordinary `hh` row with the same
accession and coordinates twice, and becomes one interaction whose two
`:INVOLVES` edges point at the one protein.

### The protein columns

A protein is a full-length human chain, or a mature viral protein excised from
a polyprotein. It is described once per row it takes part in, so the same
protein is restated hundreds of times over.

| column | notes |
|---|---|
| `accession` | UniProt accession, canonical — not an isoform. Uppercase |
| `start` | 1-based inclusive, on the accession's sequence. Always `1` for human |
| `stop` | 1-based inclusive. The sequence length for human |
| `name` | mature-protein name (`NS5A`) for viral, gene symbol (`GPX4`) for human |
| `description` | UniProt protein name. May be empty |
| `ncbi_taxon_id` | NCBI taxon id. `9606` for human. Retired ids are followed to the current one — the example's `11103` lands in the graph as `3052230` |

The restatements do not have to agree, and where they do not the **commonest
wins**, with a warning naming the protein and the variants:

- A **name or description** that changed part-way through curation — a renamed
  gene — takes its majority value.
- **Coordinates** that changed between UniProt releases take the longest span.
  This only arises for human proteins: a viral id carries its coordinates, so a
  different span there is a different protein, while a human id is a bare
  accession and the two rows are one node.

A protein whose taxon changes between rows is an error rather than a majority
vote — that is a different protein, not a restatement. Everything the warnings
report is worth fixing upstream; none of it stops a build.

`Protein.function` has no column at all — see [enriched here](#enriched-here-not-exported).

## publications.tsv *(required)*

| column | notes |
|---|---|
| `pmid` | digits only. The key — no DOIs |
| `title` | |
| `year` | |
| `journal` | may be empty |
| `authors` | one string, names separated by `;`. May be empty |
| `abstract` | may be empty |

Every `pmid` a description names must have a row here, and no pmid may appear
twice. Titles and abstracts come out of PubMed with markup in them, so this is
the file where the no-tabs-no-newlines rule usually bites.

## peptides.tsv

One row per peptide reported by a description. A description with no peptide
simply has no row; a description with three has three.

| column | notes |
|---|---|
| `stable_id` | the description's. Must appear in `descriptions.tsv` |
| `sequence` | the residues, uppercased on load |
| `source_type` | `h` or `v` |
| `source_accession`, `source_start`, `source_stop` | which of that description's two partners it comes from |

```
stable_id  sequence  source_type  source_accession  source_start  source_stop
D-00417    PSLKATC   v            P27958            1973          2419
D-00901    PSLKATC   h            P36969            1             197
```

The source columns name one of the description's two partners in full, so they
repeat that partner's own row exactly; naming anything else is an error. That
partner is the peptide's source and the other is its target — which is why
**the same sequence can appear against many sources and many targets**: the two
rows above are one `:Peptide`, a viral peptide from NS5A against GPX4 and the
same sequence as a human peptide from GPX4 against ACSL4.

**Only the sequence is stored.** The graph keeps one `:Peptide` node per unique
sequence, and the peptide's position within its source is not modelled — see
[`schema.md`](schema.md). Rows that agree once the position is dropped are the
same reported peptide, so a description reporting the same residues twice
yields one `:REPORTS` edge, not two.

## memberships.tsv *(later)*

Not yet exported — curated sets come in a later run. Which proteins belong to
which curated set. The set itself needs no file — it is created from the names
used here.

| column | notes |
|---|---|
| `set_name` | e.g. `ferroptosis` |
| `accession` | the human protein. Referencing a viral one is an error |
| *anything else* | **every further column becomes membership metadata** |

Extra columns are free-form: add `role`, `mechanism`, `curator`, whatever the
project records. An empty cell means the attribute is simply absent for that
protein, not that it is empty. Values are stored as text.

```
set_name     accession  role        mechanism
ferroptosis  P36969     inhibitor   GPX4 axis
ferroptosis  O60488     activator
```

## go_terms.tsv, go_edges.tsv, go_annotations.tsv *(not from your database)*

These are not in the relational database — they will be generated in this repo
from UniProt/GOA and the GO ontology, written into the same directory in
exactly this shape, and read by the same loader. Documented here because the
format is the contract either way.

They must carry the annotated terms **plus their full ancestor closure**, or
rolling an annotation up to a coarse process stops working.

`go_terms.tsv`

| column | notes |
|---|---|
| `go_id` | `GO:` followed by seven digits |
| `name` | |
| `namespace` | `biological_process`, `molecular_function` or `cellular_component` |
| `obsolete` | `true`/`false` (`1`/`0`, `yes`/`no` also accepted; empty means false) |

`go_edges.tsv`

| column | notes |
|---|---|
| `child_go_id`, `parent_go_id` | |
| `relation` | `IS_A` or `PART_OF` |

`go_annotations.tsv`

| column | notes |
|---|---|
| `accession` | the human protein |
| `go_id` | |
| `evidence_code` | e.g. `IDA` |
| `assigned_by` | the database that made the annotation, e.g. `UniProt`. May be empty |
| `qualifier` | GOA qualifier. `NOT` inverts the annotation, so it changes meaning. May be empty |

---

## Not exported

**Taxa have no file.** The export carries a taxon id per protein and nothing
else; the `:Taxon` nodes and the species-to-family chain are cut from the NCBI
dump this repo keeps in SQLite (`bpgraph.taxonomy`). A species links straight
to its family however many ranks lie between, and a species with no family
simply has no parent — it stays queryable, it just falls out of family
rollups. Keeping another rank is a one-line change and the chain rebuilds
itself.

### Enriched here, not exported

Two things the relational database does not hold, to be built in this repo and
written into the export directory alongside the export:

- **`function` on proteins** — the UniProt `CC FUNCTION` text. It has no column
  in `descriptions.tsv`; proteins are built with it empty and a later step
  fills it. `description` does come from the export.
- **The GO trio** — terms, ontology edges and annotations, from UniProt/GOA.
  You never write these files; they are generated in the shape above.

Until those exist, a build produces proteins with an empty `function` and no
`:GoTerm` nodes. Everything else — interactions, descriptions, peptides,
taxonomy — works from your export alone.

---

## Running it

```python
from pathlib import Path

from bpgraph import Config, build, connect
from bpgraph.loaders import TsvExport

config = Config.from_env()
export = TsvExport(Path("data/graph-2026-09-09")).load()
report = build(connect(config), export, config)
print(report.counts)
```

Loading happens before anything is written, so a malformed export fails with a
file and a line — `descriptions.tsv:2: EY0001: virus-virus interactions are not
modelled` — and the live graph is never touched. Whatever survives loading then
has to pass the constraint gate in [`build.md`](build.md).

Reconciliation warnings go through `logging`, so `logging.basicConfig()` is
what makes them visible.
