# bpgraph — export format

What to export from the relational database, as tab-separated files dropped in the **`export/`** subdirectory of a run directory under **`data/`**, which is gitignored — `data/2026-09-09/export/`. See [`schema.md`](schema.md) for what the files become, and [`build.md`](build.md) for everything else a run holds.

The export carries only what our curation alone knows: our interactions and the peptides they report. Everything a public source knows better comes from that source instead, fetched into the run beside the export — a human protein's name, description and function from Swiss-Prot, a method's name from PSI-MI, a publication's metadata from PubMed.

| file                                                | one row per                                   |
| --------------------------------------------------- | --------------------------------------------- |
| [`descriptions.tsv`](#descriptionstsv) *(required)* | observation — a pair, a publication, a method |
| [`peptides.tsv`](#peptidestsv)                      | peptide a description reports                 |

Conventions for every file:

- Tab-separated, UTF-8, one header row. Column order does not matter, names do.
- Leading and trailing whitespace is stripped from every cell.
- Every listed column must be present, and no cell may be empty except where the table says so. Empty means the empty string, never `NULL` or `\N`.
- **One line is one row, and quoting is off.** A double quote is ordinary text — but a cell may hold no tab and no newline of its own. Strip both from free text on the way out; a line that does not have the expected number of columns is rejected by its line number.

**Proteins are referenced by what curation recorded, never by an id** — the ids are derived during the build. `descriptions.tsv` and `peptides.tsv` name a partner by `accession`, `start` and `stop`, the entry and span it was observed at.

### What the build derives

The export names an entry and a span per partner; the graph's proteins are coarser. The build derives, from the columns below and [`curation/viruses.tsv`](../curation/viruses.tsv):

- **the curated virus** — the most specific row of `viruses.tsv` enclosing the entry's taxon. A viral taxon that no row encloses **fails the build**, naming the taxa to add.
- **`:Protein`** — a human accession, which must be a Swiss-Prot entry, or a curated virus plus the row's `name`. Every strain's `HBx` of HBV is one protein, and so is `nsp2` on pp1a and on pp1ab.
- **the viral vault** — every entry and span each viral protein was observed at, the entry's strain, and the entry each description used.

______________________________________________________________________

## descriptions.tsv *(required)*

One row per description: one protein pair, one publication, one method. This is also where proteins and methods come from — the file is read twice, once to gather them and once to build the descriptions against them.

| column                                    | notes                                                         |
| ----------------------------------------- | ------------------------------------------------------------- |
| `stable_id`                               | your identifier. Becomes the node's key, so it must be unique |
| `type`                                    | `hh` or `vh`                                                  |
| `pmid`                                    | digits only                                                   |
| `psimi_id`                                | a PSI-MI term, `MI:` followed by four digits                  |
| `method`                                  | the method's name. Not read: the graph names it from PSI-MI   |
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

The first two rows are the same pair by different methods. They become one `:Interaction` carrying two `:Description` nodes, and its counters record two descriptions, one publication and two method classes — which is what makes the counters a confidence signal rather than a row count.

An `hh` row is our curation of the human interactome: it is merged onto IntAct's description of the same pair, pmid and method class when IntAct has one — see [`build.md`](build.md). A `vh` row is a description of its own.

**Slot 1 is always the human partner.** Nothing else says which side is viral: a `vh` row's second partner is the viral one, every other partner is human, and an accession given as human on one row and viral on another is rejected. The build then puts the human protein on side `a` of the interaction regardless of the order it was given in.

Two viral proteins may not interact, so there is no `vv`. A pair **may** interact with itself: a homodimer is an ordinary `hh` row with the same accession and coordinates twice, and becomes one interaction whose two `:INVOLVES` edges point at the one protein.

### The protein columns

A partner is a full-length human chain, or a mature viral protein excised from a polyprotein, observed on one entry. It is described once per row it takes part in.

| column          | notes                                                                                                                         |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `accession`     | UniProt accession, canonical — not an isoform. Uppercase. A human one must be in Swiss-Prot, or the row is dropped and logged |
| `start`         | 1-based inclusive, on the accession's sequence                                                                                |
| `stop`          | 1-based inclusive                                                                                                             |
| `name`          | curated mature-protein name (`NS5A`) for viral, gene symbol for human. Case-sensitive: part of a viral protein's identity     |
| `description`   | UniProt protein name. May be empty                                                                                            |
| `ncbi_taxon_id` | NCBI taxon id. `9606` for human. Retired ids are followed to the current one — `11103` lands in the graph as `3052230`        |

Of a **human** partner only the accession is read: the rest comes from Swiss-Prot. Of a **viral** partner everything is, and the restatements do not have to agree — a description takes its commonest value, per protein and per entry. A viral protein's name is its identity, so a different name is a different protein. An accession whose taxon changes between rows is an error. The build also warns, without stopping, about viral names within one virus that differ only in case, and grouped viral proteins whose spans differ in length by more than half — members that may not be one chain.

## peptides.tsv

One row per peptide reported by a description. A description with no peptide simply has no row; a description with three has three.

| column                                            | notes                                                  |
| ------------------------------------------------- | ------------------------------------------------------ |
| `stable_id`                                       | the curated row's. Must appear in `descriptions.tsv`   |
| `sequence`                                        | the residues, uppercased on load                       |
| `source_type`                                     | `h` or `v`                                             |
| `source_accession`, `source_start`, `source_stop` | which of that description's two partners it comes from |

```
stable_id  sequence  source_type  source_accession  source_start  source_stop
D-00417    PSLKATC   v            P27958            1973          2419
D-00901    PSLKATC   h            P36969            1             197
```

The source columns name one of the description's two partners in full, so they repeat that partner's own row exactly (a human partner is matched by accession alone); naming anything else is an error. That partner is the peptide's source and the other is its target — which is why **the same sequence can appear against many sources and many targets**: the two rows above are one `:Peptide`, a viral peptide from NS5A against GPX4 and the same sequence as a human peptide from GPX4 against ACSL4.

A curated `hh` row merged onto an IntAct description brings its peptides with it.

**Only the sequence is stored.** The graph keeps one `:Peptide` node per unique sequence, and the peptide's position within its source is not modelled — see [`schema.md`](schema.md). Rows that agree once the position is dropped are the same reported peptide, so a description reporting the same residues twice from the same partner yields one `:REPORTS` edge, not two. The same residues from each partner are two edges, one per direction.

______________________________________________________________________

## Topic lists *(resolved here, per run)*

A topic is a subject of study, curated by a biologist as a spreadsheet of genes — ferroptosis, from `data/HH-Ferroptosis_completed.xlsx`. Those spreadsheets are kept untouched in `data/`, and they are too irregular to parse: each has its own columns, and cells like `EIF2AK3 (PERK)`. So each is **resolved by hand against a run's human proteins** — its Swiss-Prot — into `topics/<topic>.tsv` in the run directory, and that is what the build reads. A new run is a new directory, so its topics are resolved again.

| column          | notes                                                                |
| --------------- | -------------------------------------------------------------------- |
| `accession`     | a Swiss-Prot human accession                                         |
| *anything else* | what the topic records about it, e.g. `role`. Each topic has its own |

The file name is the topic's name. Every further column becomes a property of `:INVOLVED_IN`, as text, and must be listed for its topic in [`schema.md`](schema.md). A spreadsheet names genes, so a gene encoding two proteins — `CDKN2A`, p16INK4a and p14ARF — gets a row for each. An accession not in the run's Swiss-Prot is logged and left out. Resolve by judgment, asking about anything ambiguous, and list a new topic's columns in `schema.md` and in `TOPIC_PROPERTIES` in `audit.py`.

```
accession  role
P42771     suppressor
Q8N726     suppressor
Q9NZJ5     suppressor
```

______________________________________________________________________

______________________________________________________________________

## Loading it

Loading happens before anything is written, so a malformed export fails with a file and a line — `descriptions.tsv:2: EY0001: virus-virus interactions are not modelled` — and the live graph is never touched. Whatever survives loading then has to pass the constraint gate in [`build.md`](build.md).

Reconciliation warnings go through `logging`, so `logging.basicConfig()` is what makes them visible.
