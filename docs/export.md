# bpgraph — export format

What the relational database exports, as tab-separated files dropped in the **`export/`** subdirectory of a run directory under **`data/`**, which is gitignored — `data/2026-10-14/export/`. See [`schema.md`](schema.md) for what the files become, and [`build.md`](build.md) for everything else a run holds.

The export carries only what our curation alone knows: our interactions, how the viral proteins they name are grouped, the viral sequences, and the sequences the interactions map. Everything a public source knows better comes from that source instead, fetched into the run beside the export — a human protein's name and function from Swiss-Prot, a viral entry's function text from UniProt, a method's name from PSI-MI, a publication's metadata from PubMed.

| file                                                  | one row per                                        |
| ----------------------------------------------------- | -------------------------------------------------- |
| [`descriptions_hh`](#descriptions_hh-descriptions_vh) | human–human observation — a pair, a pmid, a method |
| [`descriptions_vh`](#descriptions_hh-descriptions_vh) | virus–human observation                            |
| [`interactors_viral`](#interactors_viral)             | viral entry and span a VH row names                |
| [`mappings_h`, `mappings_v`](#mappings_h-mappings_v)  | sequence a description maps on one of its partners |

The database names each file after the run that wrote it, `descriptions_hh_run87.tsv`: the build finds a file by its stem, and an export must hold exactly one `descriptions_hh*.tsv`, and so on. All five are required. The database also writes an `.xlsx` copy of each, which the build ignores.

Conventions for every file:

- Tab-separated, UTF-8, one header row. Column order does not matter, names do. A column the build does not read may be there.
- Leading and trailing whitespace is stripped from every cell.
- Every column the build reads must be present, and no cell it reads may be empty except where the table says so. Empty means the empty string, never `NULL` or `\N`.
- **One line is one row, and quoting is off.** A double quote is ordinary text — but a cell may hold no tab and no newline of its own. Strip both from free text on the way out; a line that does not have the expected number of columns is rejected by its line number.

**UniProt entries are the ones curation recorded.** A human accession is a Swiss-Prot entry of the current release. A viral entry may be of any release: curation matches its entries to the current UniProt where it can, and keeps the recorded one where it cannot. Each partner says which release it is of, in `release1` and `release2`, and a viral site's coordinates and sequence are that release's.

### What curation decides, and what the build derives

Curation groups the viral proteins. A viral partner's **virus** is the species taxon in `species_ncbi_taxon_id`, named `species`, and its **protein** is the virus plus `protein`, a name grouping its curated forms: HBV's `X` and `HBx` are both `HBx`, EBV's `EBNA6` is `EBNA3C`. The build takes the grouping as given. From it, the build derives:

- **`:Protein`** — a human accession, which must be a Swiss-Prot entry, or a virus plus a `protein`. Every strain's `HBx` of HBV is one protein, and so is `nsp2` on pp1a and on pp1ab.
- **`:Virus` and its family** — a virus for each species taxon a kept VH row names, and the NCBI family above it, found in the run's taxonomy after following NCBI's merges. A species taxon the taxonomy does not know **fails the build**: refetch the taxonomy.
- **the viral vault** — every entry and span each viral protein was observed at with its sequence, the entry's strain and release, and the entry each description used.

______________________________________________________________________

## descriptions_hh, descriptions_vh

One row per description: one protein pair, one publication, one method. The file says the type: `descriptions_hh` is human–human, `descriptions_vh` virus–human. A `stable_id` is unique across the two.

Columns both files share:

| column                   | notes                                                                   |
| ------------------------ | ----------------------------------------------------------------------- |
| `stable_id`              | curation's identifier. Becomes the node's key, so unique                |
| `pmid`                   | digits only                                                             |
| `psimi_id`               | a PSI-MI term, `MI:` followed by four digits                            |
| `accession1`             | the first partner — always human                                        |
| `version`, `method`      | not read: the row's revision, and the method's name, which PSI-MI gives |
| `release1`, `gene_name1` | not read: Swiss-Prot gives the current name                             |

`descriptions_hh` names its second partner, human, the same way: `accession2`, with `release2` and `gene_name2` unread.

`descriptions_vh` names its viral partner:

| column                             | notes                                                                        |
| ---------------------------------- | ---------------------------------------------------------------------------- |
| `accession2`, `start2`, `stop2`    | the entry and span it was observed at, 1-based inclusive                     |
| `release2`                         | the UniProt release of the entry; must be its row of `interactors_viral`'s   |
| `protein`                          | the curated protein name. Case-sensitive: part of the protein's identity     |
| `species_ncbi_taxon_id`, `species` | the virus: the species taxon curation groups the protein under, and its name |
| `strain_ncbi_taxon_id`, `strain`   | the entry's strain, kept in the vault. `strain` may be empty                 |
| `uniprot_name2`, `generic_name2`   | not read                                                                     |

```
descriptions_vh_run87.tsv (some columns)
stable_id   pmid      psimi_id  accession1  species_ncbi_taxon_id  species            protein  strain_ncbi_taxon_id  release2  accession2  start2  stop2
EY00003F06  41898490  MI:0069   P05388      3050299                Epstein-Barr virus  BGLF4    10377                 2019_01   P13288      1       429
```

Rows of one pair by different methods become one `:Interaction` carrying a `:Description` each, and its counters record them.

An `hh` row is our curation of the human interactome: it is merged onto IntAct's description of the same pair and pmid when IntAct has one — see [`build.md`](build.md). A `vh` row is a description of its own.

**Slot 1 is always the human partner.** A `vh` row's second partner is the viral one, and every other partner is human. The build puts the human protein on side `a` of the interaction regardless.

Two viral proteins may not interact, so there is no `vv`. A pair **may** interact with itself: a homodimer is an ordinary `hh` row with the same accession twice, and becomes one interaction whose two `:INVOLVES` edges point at the one protein.

A human accession is canonical — not an isoform — and must be a Swiss-Prot entry, or the row is dropped and logged. The rows observing one viral site must agree on its `protein`, its virus, its strain and its release, and a virus has one name; either disagreement fails the build. Its function text is UniProt's, fetched for the entry and span, and every distinct one its members carry is kept — see [`schema.md`](schema.md). The build also warns, without stopping, about viral proteins whose members carry several texts, names within one virus that differ only in case, and members whose spans differ in length by more than half — members that may not be one chain.

## interactors_viral

One row per viral entry and span a `vh` row names, and its residues. Every viral partner of `descriptions_vh` must have its row, or the load fails. The sequences go to the viral vault, not the graph.

| column                       | notes                                                 |
| ---------------------------- | ----------------------------------------------------- |
| `accession`, `start`, `stop` | the entry and span, as the descriptions name them     |
| `release`                    | the UniProt release the sequence is from              |
| `sequence`                   | the residues of that span, exactly `stop - start + 1` |

```
release  accession   start  stop  sequence
2019_01  P27958      1973   2419  SGSWLRDVWDWICTVLTDFKTWLQSKLLPRLPGVPFFSCQRGYKGVWRGDGIMQTTCPC…
```

## mappings_h, mappings_v

One row per sequence a description maps on one of its partners: the region it reports as sufficient for the interaction. `mappings_h` holds the ones on a human partner, `mappings_v` the ones on a viral partner. A description may have none, or several.

| column                               | notes                                                                        |
| ------------------------------------ | ---------------------------------------------------------------------------- |
| `stable_id`                          | the description's. Must appear in a description file                         |
| `sequence`                           | the residues, uppercased on load, taken as given                             |
| `accession`                          | the partner it is on, which must be one of the description's two             |
| `start`, `stop`                      | `mappings_v` only: the viral partner's span, which must be the description's |
| `target`                             | `mappings_h` only: `h` or `v`, the kind of the partner the sequence binds    |
| `isoform`, `release`, `nter`, `cter` | not read                                                                     |

**Only peptides are kept: a sequence of 5 to 20 residues, both included.** A longer or shorter mapping is skipped without being checked further. A mapping on an isoform is its entry's: the peptide comes from the protein, whichever isoform it was mapped on. Its `nter` and `cter` are ignored, and its sequence is taken as given, a lowercase residue included.

The partner a peptide is on is its source, and the other partner is its target — which is why **the same sequence can appear against many sources and many targets**, and why one sequence is one `:Peptide`. A human source is matched by accession alone; in a homodimer it is both partners, and its peptide binds its own source.

```
mappings_v_run87.tsv
stable_id   sequence        release  accession  start  stop  isoform  nter  cter
EY294151C6  mSTNPKPQRKTKRNT 2019_01  Q99IB8     2      191   Q99IB8   M
```

**Only the sequence is stored.** The graph keeps one `:Peptide` node per unique sequence, and the peptide's position within its source is not modelled — see [`schema.md`](schema.md). Rows that agree once the position is dropped are the same reported peptide, so a description reporting the same residues twice from the same partner yields one `:REPORTS` edge, not two.

A curated `hh` row merged onto an IntAct description brings its peptides with it.

______________________________________________________________________

## Topic lists

Topic lists — a subject of study such as ferroptosis, curated as a spreadsheet of genes — are not part of the export or the build. The graph does not hold them: a query takes a topic's Swiss-Prot accessions as a parameter.

______________________________________________________________________

## Loading it

Loading happens before anything is written, so a malformed export fails with a file and a line — `descriptions_vh_run87.tsv:2: MI:9999 is not a PSI-MI term` — and the live graph is never touched. Whatever survives loading then has to pass the constraint gate in [`build.md`](build.md).

Reconciliation warnings go through `logging`, so `logging.basicConfig()` is what makes them visible.
