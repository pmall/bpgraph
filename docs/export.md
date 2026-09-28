# bpgraph — export format

What to export from the relational database, as tab-separated files dropped in the **`export/`** subdirectory of a run directory under **`data/`**, which is gitignored — `data/2026-09-09/export/`. See [`schema.md`](schema.md) for what the files become, and [`build.md`](build.md) for everything else a run holds.

The export carries only what our curation alone knows: our interactions, the viral proteins they name with their sequences, and the peptides they report. Everything a public source knows better comes from that source instead, fetched into the run beside the export — a protein's UniProt name and function, a method's name from PSI-MI, a publication's metadata from PubMed.

| file                                                             | one row per                                        |
| ---------------------------------------------------------------- | -------------------------------------------------- |
| [`descriptions_hh.tsv`](#descriptions_hhtsv-descriptions_vhtsv) | human–human observation — a pair, a pmid, a method |
| [`descriptions_vh.tsv`](#descriptions_hhtsv-descriptions_vhtsv) | virus–human observation                            |
| [`viral_proteins.tsv`](#viral_proteinstsv)                       | viral entry and span a VH row names                |
| [`peptides.tsv`](#peptidestsv)                                   | peptide a description reports                      |

All four are required; `peptides.tsv` may have no rows.

Conventions for every file:

- Tab-separated, UTF-8, one header row. Column order does not matter, names do.
- Leading and trailing whitespace is stripped from every cell.
- Every listed column must be present, and no cell may be empty except where the table says so. Empty means the empty string, never `NULL` or `\N`.
- **One line is one row, and quoting is off.** A double quote is ordinary text — but a cell may hold no tab and no newline of its own. Strip both from free text on the way out; a line that does not have the expected number of columns is rejected by its line number.

**Proteins are referenced by what curation recorded, never by an id** — the ids are derived during the build. Every file names a partner by `accession`, `start` and `stop`, the entry and span it was observed at.

### What the build derives

The export names an entry and a span per partner; the graph's proteins are coarser. The build derives, from the columns below and [`curation/viruses.tsv`](../curation/viruses.tsv):

- **the curated virus** — the most specific row of `viruses.tsv` enclosing the entry's taxon. A viral taxon that no row encloses **fails the build**, naming the taxa to add.
- **`:Protein`** — a human accession, which must be a Swiss-Prot entry, or a curated virus plus the row's `name`. Every strain's `HBx` of HBV is one protein, and so is `nsp2` on pp1a and on pp1ab.
- **the viral vault** — every entry and span each viral protein was observed at with its sequence, the entry's strain, and the entry each description used.

______________________________________________________________________

## descriptions_hh.tsv, descriptions_vh.tsv

One row per description: one protein pair, one publication, one method. The file says the type: `descriptions_hh.tsv` is human–human, `descriptions_vh.tsv` virus–human. Both have the same columns, and a `stable_id` is unique across the two.

| column                              | notes                                                         |
| ----------------------------------- | ------------------------------------------------------------- |
| `stable_id`                         | your identifier. Becomes the node's key, so it must be unique |
| `pmid`                              | digits only                                                   |
| `psimi_id`                          | a PSI-MI term, `MI:` followed by four digits                  |
| `accession1`, `start1`, `stop1`     | the first partner — always human                              |
| `name1`, `ncbi_taxon_id1`           | and how it is named                                           |
| `accession2`, `start2`, `stop2`     | the second partner — viral in `descriptions_vh.tsv`           |
| `name2`, `ncbi_taxon_id2`           | and how it is named                                           |

```
descriptions_vh.tsv
stable_id  pmid      psimi_id  accession1  start1  stop1  name1  ncbi_taxon_id1  accession2  start2  stop2  name2  ncbi_taxon_id2
D-00417    12345678  MI:0018   P36969      1       197    GPX4   9606            P27958      1973    2419   NS5A   11103
D-00418    12345678  MI:0006   P36969      1       197    GPX4   9606            P27958      1973    2419   NS5A   11103

descriptions_hh.tsv
stable_id  pmid      psimi_id  accession1  start1  stop1  name1  ncbi_taxon_id1  accession2  start2  stop2  name2  ncbi_taxon_id2
D-00901    22222222  MI:0006   P36969      1       197    GPX4   9606            O60488      1       711    ACSL4  9606
```

The two VH rows are the same pair by different methods. They become one `:Interaction` carrying two `:Description` nodes, and its counters record two descriptions, one publication and two method classes — which is what makes the counters a confidence signal rather than a row count.

An `hh` row is our curation of the human interactome: it is merged onto IntAct's description of the same pair, pmid and method class when IntAct has one — see [`build.md`](build.md). A `vh` row is a description of its own.

**Slot 1 is always the human partner.** Nothing else says which side is viral: a `vh` row's second partner is the viral one, and every other partner is human. The build then puts the human protein on side `a` of the interaction regardless of the order it was given in.

Two viral proteins may not interact, so there is no `vv`. A pair **may** interact with itself: a homodimer is an ordinary `hh` row with the same accession and coordinates twice, and becomes one interaction whose two `:INVOLVES` edges point at the one protein.

### The protein columns

A partner is a full-length human chain, or a mature viral protein excised from a polyprotein, observed on one entry. It is named once per row it takes part in.

| column          | notes                                                                                                                         |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `accession`     | UniProt accession, canonical — not an isoform. Uppercase. A human one must be in Swiss-Prot, or the row is dropped and logged |
| `start`         | 1-based inclusive, on the accession's sequence                                                                                |
| `stop`          | 1-based inclusive                                                                                                             |
| `name`          | curated mature-protein name (`NS5A`) for viral, gene symbol for human. Case-sensitive: part of a viral protein's identity     |
| `ncbi_taxon_id` | NCBI taxon id. `9606` for human. Retired ids are followed to the current one — `11103` lands in the graph as `3052230`        |

Of a **human** partner only the accession is read: the rest comes from Swiss-Prot. Of a **viral** partner everything is, and it must match its row of `viral_proteins.tsv`. A viral protein's name is its identity, so a different name is a different protein; its description and function text are UniProt's, fetched per entry and span, and every distinct one its members carry is kept — see [`schema.md`](schema.md). An accession whose taxon changes between rows is an error. The build also warns, without stopping, about viral proteins whose members carry several texts, names within one virus that differ only in case, and members whose spans differ in length by more than half — members that may not be one chain.

## viral_proteins.tsv

One row per viral entry and span a `vh` row names: the mature protein as curation holds it, and its residues. Every viral partner of `descriptions_vh.tsv` must have its row, under the same name and taxon, or the load fails. The sequences go to the viral vault, not the graph.

| column                         | notes                                                   |
| ------------------------------ | ------------------------------------------------------- |
| `accession`, `start`, `stop`   | the entry and span, as the descriptions name them       |
| `name`, `ncbi_taxon_id`        | as the descriptions name them                           |
| `sequence`                     | the residues of that span, exactly `stop - start + 1`   |

```
accession  start  stop  name  ncbi_taxon_id  sequence
P27958     1973   2419  NS5A  11103          SGSWLRDVWDWICTVLTDFKTWLQSKLLPRLPGVPFFSCQRGYKGVWRGDGIMQTTCPC…
```

## peptides.tsv

One row per peptide reported by a description. A description with no peptide simply has no row; a description with three has three.

| column                                            | notes                                                  |
| ------------------------------------------------- | ------------------------------------------------------ |
| `stable_id`                                       | the curated row's. Must appear in a description file   |
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

## Topic lists

Topic lists — a subject of study such as ferroptosis, curated as a spreadsheet of genes — are not part of the export or the build. The graph does not hold them: a query takes a topic's Swiss-Prot accessions as a parameter.

______________________________________________________________________

______________________________________________________________________

## Loading it

Loading happens before anything is written, so a malformed export fails with a file and a line — `descriptions_vh.tsv:2: MI:9999 is not a PSI-MI term` — and the live graph is never touched. Whatever survives loading then has to pass the constraint gate in [`build.md`](build.md).

Reconciliation warnings go through `logging`, so `logging.basicConfig()` is what makes them visible.
