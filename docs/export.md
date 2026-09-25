# bpgraph — export format

What to export from the relational database, as tab-separated files dropped in the **`export/`** subdirectory of a run directory under **`data/`**, which is gitignored — `data/2026-09-09/export/`. `bpgraph.loaders.tsv.TsvExport` reads one run directory; see [`schema.md`](schema.md) for what the files become.

Three files carry the whole export. There is no protein table and no method table: a description row restates its two partners and its detection method inline, and the build reconciles the repeats.

| file                                                | one row per                                   |
| --------------------------------------------------- | --------------------------------------------- |
| [`descriptions.tsv`](#descriptionstsv) *(required)* | observation — a pair, a publication, a method |
| [`publications.tsv`](#publicationstsv) *(required)* | publication                                   |
| [`peptides.tsv`](#peptidestsv)                      | peptide a description reports                 |

Conventions for every file:

- Tab-separated, UTF-8, one header row. Column order does not matter, names do.
- Leading and trailing whitespace is stripped from every cell.
- Every listed column must be present, and no cell may be empty except where the table says so. Empty means the empty string, never `NULL` or `\N`.
- **One line is one row, and quoting is off.** A double quote is ordinary text, so abstracts keep theirs — but a cell may hold no tab and no newline of its own. Strip both from free text on the way out; a line that does not have the expected number of columns is rejected by its line number.

[`docs/example-export/`](example-export) holds a small working example of every file this document asks you for, and every snippet in the sections below is a row from it. Loading that directory builds the graph [`queries.md`](queries.md) walks through. It is laid out as a run directory, with the GO trio this repo [generates](#generated-here-not-exported) beside `export/`, but carries no taxonomy, so it borrows a real run's:

```python
taxonomy = Taxonomy.open(Run(Path("data/2026-09-09")).taxonomy)
TsvExport(Run(Path("docs/example-export")), taxonomy, CuratedViruses.load(taxonomy))
```

**Proteins are referenced by what curation recorded, never by an id** — the ids are derived during the build. `descriptions.tsv` and `peptides.tsv` name a partner by `accession`, `start` and `stop`, the entry and span it was observed at. The GO annotations apply only to human proteins, and a human accession identifies exactly one of those, so they carry `accession` alone.

### What the build derives

The export names an entry and a span per partner; the graph's proteins are coarser. The build derives, from the columns below and [`curation/viruses.tsv`](../curation/viruses.tsv):

- **`:Entry`** — one per accession, with its taxon and description.
- **the curated virus** — the most specific row of `viruses.tsv` enclosing the entry's taxon. A viral taxon that no row encloses **fails the build**, naming the taxa to add.
- **`:Protein`** — a human accession, or a curated virus plus the row's `name`. Every strain's `HBx` of HBV is one protein, and so is `nsp2` on pp1a and on pp1ab.
- **`:ON_ENTRY`** — every entry and span each viral protein was observed at, and each human protein's one entry.

A description keeps the entry each side was observed on, as `:OBSERVED_ON`.

______________________________________________________________________

## descriptions.tsv *(required)*

One row per description: one protein pair, one publication, one method. This is also where proteins and methods come from — the file is read twice, once to gather them and once to build the descriptions against them.

| column                                    | notes                                                         |
| ----------------------------------------- | ------------------------------------------------------------- |
| `stable_id`                               | your identifier. Becomes the node's key, so it must be unique |
| `type`                                    | `hh` or `vh`                                                  |
| `pmid`                                    | must appear in `publications.tsv`                             |
| `psimi_id`                                | `MI:` followed by four digits                                 |
| `method`                                  | the method's name, e.g. `two hybrid`                          |
| `accession1`, `start1`, `stop1`           | the first partner — always human                              |
| `name1`, `description1`, `ncbi_taxon_id1` | and how it is described                                       |
| `accession2`, `start2`, `stop2`           | the second partner — viral exactly when `type` is `vh`        |
| `name2`, `description2`, `ncbi_taxon_id2` | and how it is described                                       |

```
stable_id  type  pmid      psimi_id  method       accession1  start1  stop1  name1  description1           ncbi_taxon_id1  accession2  start2  stop2  name2  description2        ncbi_taxon_id2
D-00417    vh    12345678  MI:0018   two hybrid   P36969      1       197    GPX4   Phospholipid hydrope…  9606            P27958      1973    2419   NS5A   Genome polyprotein  11103
D-00418    vh    12345678  MI:0006   anti bait…   P36969      1       197    GPX4   Phospholipid hydrope…  9606            P27958      1973    2419   NS5A   Genome polyprotein  11103
D-00901    hh    22222222  MI:0006   anti bait…   P36969      1       197    GPX4   Phospholipid hydrope…  9606            O60488      1       711    ACSL4  Long-chain-fatty-a…  9606
```

The first two rows are the same pair by different methods. They become one `:Interaction` carrying two `:Description` nodes, and its counters record two descriptions, one publication and two methods — which is what makes the counters a confidence signal rather than a row count.

**Slot 1 is always the human partner.** Nothing else says which side is viral: a `vh` row's second partner is the viral one, every other partner is human, and an accession given as human on one row and viral on another is rejected. The build then puts the human protein on side `a` of the interaction regardless of the order it was given in.

Two viral proteins may not interact, so there is no `vv`. A pair **may** interact with itself: a homodimer is an ordinary `hh` row with the same accession and coordinates twice, and becomes one interaction whose two `:INVOLVES` edges point at the one protein.

### The protein columns

A partner is a full-length human chain, or a mature viral protein excised from a polyprotein, observed on one entry. It is described once per row it takes part in, so the same protein is restated hundreds of times over.

| column          | notes                                                                                                                                |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `accession`     | UniProt accession, canonical — not an isoform. Uppercase                                                                             |
| `start`         | 1-based inclusive, on the accession's sequence. Always `1` for human                                                                 |
| `stop`          | 1-based inclusive. The sequence length for human                                                                                     |
| `name`          | curated mature-protein name (`NS5A`) for viral, gene symbol (`GPX4`) for human. Case-sensitive: part of a viral protein's identity   |
| `description`   | UniProt protein name. May be empty                                                                                                   |
| `ncbi_taxon_id` | NCBI taxon id. `9606` for human. Retired ids are followed to the current one — the example's `11103` lands in the graph as `3052230` |

The restatements do not have to agree, and where they do not the **commonest wins**:

- A human protein's **name** that changed part-way through curation — a renamed gene — takes its majority value. A viral protein's name is its identity, so a different name there is a different protein.
- A **description** takes its majority value, per protein and per entry.
- A human entry's **coordinates** that changed between UniProt releases take the longest span, with a warning. A viral protein keeps every span it was observed at, one `:ON_ENTRY` each.

An accession whose taxon changes between rows is an error rather than a majority vote. The build also warns, without stopping, about viral names within one virus that differ only in case, and grouped viral proteins whose spans differ in length by more than half — members that may not be one chain.

`Protein.function` has no column at all — it is fetched from UniProt, not exported; see [generated here](#generated-here-not-exported).

## publications.tsv *(required)*

| column     | notes                                            |
| ---------- | ------------------------------------------------ |
| `pmid`     | digits only. The key — no DOIs                   |
| `title`    |                                                  |
| `year`     |                                                  |
| `journal`  | may be empty                                     |
| `authors`  | one string, names separated by `;`. May be empty |
| `abstract` | may be empty                                     |

Every `pmid` a description names must have a row here, and no pmid may appear twice. Titles and abstracts come out of PubMed with markup in them, so this is the file where the no-tabs-no-newlines rule usually bites.

## peptides.tsv

One row per peptide reported by a description. A description with no peptide simply has no row; a description with three has three.

| column                                            | notes                                                  |
| ------------------------------------------------- | ------------------------------------------------------ |
| `stable_id`                                       | the description's. Must appear in `descriptions.tsv`   |
| `sequence`                                        | the residues, uppercased on load                       |
| `source_type`                                     | `h` or `v`                                             |
| `source_accession`, `source_start`, `source_stop` | which of that description's two partners it comes from |

```
stable_id  sequence  source_type  source_accession  source_start  source_stop
D-00417    PSLKATC   v            P27958            1973          2419
D-00901    PSLKATC   h            P36969            1             197
```

The source columns name one of the description's two partners in full, so they repeat that partner's own row exactly (a human partner is matched by accession alone); naming anything else is an error. That partner is the peptide's source and the other is its target — which is why **the same sequence can appear against many sources and many targets**: the two rows above are one `:Peptide`, a viral peptide from NS5A against GPX4 and the same sequence as a human peptide from GPX4 against ACSL4.

**Only the sequence is stored.** The graph keeps one `:Peptide` node per unique sequence, and the peptide's position within its source is not modelled — see [`schema.md`](schema.md). Rows that agree once the position is dropped are the same reported peptide, so a description reporting the same residues twice from the same partner yields one `:REPORTS` edge, not two. The same residues from each partner are two edges, one per direction.

## The GO trio *(not from your database)*

These are not in the relational database. They are generated in this repo from GOA and the GO ontology and written into the run directory beside the function text, by `uv run bpgraph-go <run directory>` — see [generated here](#generated-here-not-exported) for the naming and the sources. Documented here because the shape is the contract either way.

They carry the annotated terms **plus their full ancestor closure**, or rolling an annotation up to a coarse process stops working. The three are written together against one ontology release and are read the same way: an edge names two terms and an annotation names one, so the loader rejects a `go_id` that has no row in the terms file, and rejects finding some of the three without the others.

`go_terms.tsv`

| column      | notes                                                                 |
| ----------- | --------------------------------------------------------------------- |
| `go_id`     | `GO:` followed by seven digits                                        |
| `name`      |                                                                       |
| `namespace` | `biological_process`, `molecular_function` or `cellular_component`    |
| `obsolete`  | `true`/`false` (`1`/`0`, `yes`/`no` also accepted; empty means false) |

`go_edges.tsv`

| column                        | notes                                  |
| ----------------------------- | -------------------------------------- |
| `child_go_id`, `parent_go_id` | both must have a row in `go_terms.tsv` |
| `relation`                    | `IS_A` or `PART_OF`                    |

`go_annotations.tsv`

| column          | notes                                                                            |
| --------------- | -------------------------------------------------------------------------------- |
| `accession`     | the human protein. Viral proteins are not annotated — see below                  |
| `go_id`         |                                                                                  |
| `evidence_code` | e.g. `IDA`                                                                       |
| `assigned_by`   | the database that made the annotation, e.g. `UniProt`. May be empty              |
| `qualifier`     | GOA qualifier. `NOT` inverts the annotation, so it changes meaning. May be empty |

______________________________________________________________________

## Not exported

**Taxa have no file in the export.** It carries a taxon id per partner and nothing else. The curated viruses come from [`curation/viruses.tsv`](../curation/viruses.tsv), kept in this repo, and the virus-to-family edge from the NCBI dump this repo fetches into the run directory and keeps in SQLite (`bpgraph.taxonomy`). A virus with no family simply has no parent — it stays queryable, it just falls out of family rollups.

### Generated here, not exported

Two things the relational database does not hold, built in this repo from UniProt and GO and written into **the run directory, beside `export/` rather than in it**, so `export/` stays exactly what your database produced:

- **`functions.tsv`** — `function` on proteins, the UniProt `CC FUNCTION` text. It has no column in `descriptions.tsv`; `description` does come from the export. Written by `uv run bpgraph-functions <run directory>`, which reads that export to learn which entries and spans to fetch.
- **`go_terms.tsv`, `go_edges.tsv` and `go_annotations.tsv`** — the GO an export's human proteins reach. Written by `uv run bpgraph-go <run directory>`, which reads that export to learn which proteins to cut the ontology down to.

A run without them loads all the same: its proteins land with an empty `function` and it gets no `:GoTerm` nodes, with a line in the log saying so. Everything else — interactions, descriptions, peptides, entries — works from your export, the taxonomy and the curated virus list alone.

#### functions.tsv

**Fetched into the run directory of the export it was fetched for**, so a new export cannot quietly read the last one's text: a new export is a new run directory, with a file that is not there yet — fetch again.

| column                       | notes                                                     |
| ---------------------------- | --------------------------------------------------------- |
| `type`                       | `h` or `v`                                                |
| `accession`, `start`, `stop` | an entry and span, exactly as `descriptions.tsv` gives it |
| `function`                   | the text. A span with none has no row                     |

```
type  accession  start  stop  function
h     P36969     1      197   Essential antioxidant peroxidase that directly…
v     P27958     1973   2419  Phosphorylated protein that is indispensable f…
```

A row is one entry and span, not one protein: a viral protein observed on several entries has several rows, and the build pools them into its one `function` — the commonest text, weighted by how many descriptions saw each entry — logging every protein whose entries disagree. A UniProt entry is one accession, and a viral polyprotein holds a mature protein per chain. UniProt scopes a FUNCTION comment to a chain by naming its molecule, and the fetcher matches the two **by coordinates rather than by name** — curation and UniProt disagree about the exact boundary often enough, the row above being one residue short of UniProt's NS5A chain, while two chains of one entry never sit close enough for the overlap to be ambiguous. A span covering several chains, a whole polyprotein being the usual case, takes all of their text, each paragraph under its chain's name.

**Only text about the span is written.** An entry's own FUNCTION describes the whole accession, so it is used only where the export names no other part of that accession. Where a polyprotein is cut into mature proteins by an entry UniProt never split into chains, there is nothing to say about any one of them, and they all keep `function` empty rather than sharing one text. Accessions UniProt has retired — deleted, or merged into another — come back with nothing and land the same way.

A row naming a span the export does not have means the file and the export beside it have parted ways — the export was rebuilt in place, most likely — and the loader rejects it by its line number rather than loading half-stale text.

#### The GO trio

Kept the same way and for the same reason, and cut from two dumps `bpgraph-go` fetches into the run directory the way the taxonomy is fetched:

- **`go-basic.obo`**, the ontology, from the Gene Ontology's current release. It is the version filtered to the relations annotations propagate over and guaranteed acyclic. Only `is_a` and `part_of` are kept of those: a protein involved in `regulation of X` is not involved in `X`, so the three `regulates` relations would make a rollup say things the annotations do not.
- **`goa_human.gaf.gz`**, every GO annotation on the human reference proteome, from the EBI. It carries the evidence code, the qualifier and the assigning database, so no per-protein request is needed; everything the export does not name is dropped as the file goes past.

Both are reissued regularly, so each run directory fetches its own, at least as recent as its export, and every fetch after the first reuses it.

Terms are written with the **full ancestor closure** above every annotated one — for the 2026-09-09 export, 20,720 of GO's 48,340 terms — so rolling an annotation up to a coarse process is a traversal rather than a lookup table. All three namespaces are written, and a query cuts to the one it wants with `namespace`, which is indexed.

**Human proteins only.** GOA does annotate viral proteins, but it annotates a whole accession, while a viral protein here is one mature chain excised from a polyprotein and nothing in GOA says which chain a term belongs to. The function text gets away with it because UniProt scopes a FUNCTION comment to a chain by naming its molecule; there is no equivalent here, so `go_annotations` naming a viral protein is an error rather than a guess.

An accession UniProt has retired, or that is not in the reference proteome, simply has no annotation — 16,931 of the 2026-09-09 export's 17,222 human proteins do.

## Topic lists *(resolved here, per run)*

A topic is a subject of study, curated by a biologist as a spreadsheet of genes — ferroptosis, from `data/HH-Ferroptosis_completed.xlsx`. Those spreadsheets are kept untouched in `data/`, and they are too irregular to parse: each has its own columns, and cells like `EIF2AK3 (PERK)`. So each is **resolved by hand against a run's export** into `topics/<topic>.tsv` in the run directory, and that is what the build reads. A new export is a new run directory, so its topics are resolved again, against the proteins it actually has.

| column          | notes                                                                |
| --------------- | -------------------------------------------------------------------- |
| `accession`     | a human protein of this export                                       |
| *anything else* | what the topic records about it, e.g. `role`. Each topic has its own |

The file name is the topic's name. Every further column becomes a property of `:INVOLVED_IN`, as text, and must be listed for its topic in [`schema.md`](schema.md). A spreadsheet names genes, so a gene encoding two proteins — `CDKN2A`, p16INK4a and p14ARF — gets a row for each. An accession the export does not have is logged and left out. Resolve by judgment, asking about anything ambiguous, and list a new topic's columns in `schema.md` and in `TOPIC_PROPERTIES` in `audit.py`.

```
accession  role
P42771     suppressor
Q8N726     suppressor
Q9NZJ5     suppressor
```

______________________________________________________________________

## Running it

A run directory holds the export and everything fetched for it:

```
data/2026-09-09/
  export/            descriptions.tsv, publications.tsv, peptides.tsv
  sources.tsv        which release of each dataset was fetched
  taxdmp.zip         taxonomy.sqlite
  functions.tsv
  go-basic.obo       goa_human.gaf.gz
  go_terms.tsv       go_edges.tsv       go_annotations.tsv
  topics/            ferroptosis.tsv
```

Fetch the taxonomy first — the other two read the export, which resolves viruses against it — then build:

```sh
uv run bpgraph-taxonomy data/2026-09-09     # -> taxdmp.zip, taxonomy.sqlite
uv run bpgraph-functions data/2026-09-09    # -> functions.tsv
uv run bpgraph-go data/2026-09-09           # -> go_{terms,edges,annotations}.tsv
uv run bpgraph-build data/2026-09-09        # -> the live graph
```

Every fetch records its dataset in `sources.tsv`: the URL, the day it was fetched, and the release the source names — the taxdump's `Last-Modified`, UniProt's `X-UniProt-Release`, the ontology's `data-version`, the GOA dump's `date-generated`. `bpgraph-build` prints them after the counts.

Loading happens before anything is written, so a malformed export fails with a file and a line — `descriptions.tsv:2: EY0001: virus-virus interactions are not modelled` — and the live graph is never touched. Whatever survives loading then has to pass the constraint gate in [`build.md`](build.md).

Reconciliation warnings go through `logging`, so `logging.basicConfig()` is what makes them visible.
