# Curating the virus list — the process

How [`viruses.tsv`](viruses.tsv) is produced, so a later session can redo it against a new export with the same rules. [`NAMING.md`](NAMING.md) says *why* each rule is what it is; this file says *what to do*. The code is not kept: a short script per step is enough, and the rules below are the contract.

## When to redo it

- **A build fails at the curated-virus gate.** The export has viral taxa no row encloses, and the error names them. Usually the fix is to **add rows** for them by the rules below, not to regenerate the list.
- **A deliberate review**, e.g. a new ICTV release, or revisiting a grouping call such as `IAV`.

Regenerating the whole list can move groups and rename viruses, which changes protein ids (`{taxon_id}:{name}`) in the graph. Diff the new list against the old one, keep existing rows where the rules still hold, and treat every change as a decision.

## Inputs

1. **The viral taxa of the export.** Every `ncbi_taxon_id2` of a `vh` row in `descriptions.tsv`, followed through NCBI's `merged.dmp` to its current id. For each, count its distinct viral proteins and its interactions: the counts drive the review, and end up as the informational columns.
2. **The NCBI taxonomy dump** (`taxdmp.zip`, fetched by `bpgraph-taxonomy` into the run directory): `nodes.dmp` for parents and ranks, `names.dmp` for the `scientific name`, `acronym` and `genbank acronym` of each node, `merged.dmp` for retired ids.
3. **The ICTV Virus Metadata Resource** (VMR), the spreadsheet at `https://ictv.global/vmr`. Use the sheet of the current release (`VMR MSL41` for the first list) and only its exemplar rows (`Exemplar or additional isolate` = `E`), one per species: `Species` → `Virus name abbreviation(s)`. Record which MSL was used.

## Steps

### 1. Place every taxon

For each viral taxon, walk its lineage to the root and note:

- its **species**: the nearest ancestor-or-self of rank `species`;
- its **family**: the nearest of rank `family`;
- its **path below the species**: the nodes from the taxon up to, not including, the species — strains, isolates, serotypes, `no rank` nodes.

A taxon with no species ancestor is its own group.

### 2. Review the species

For every species, print the tree of the export's taxa beneath it, each node with its interaction and protein totals and its NCBI acronyms. This is what a person reads to decide the splits in step 3: a species holding several conventionally distinct viruses shows up as sibling subtrees that each carry a familiar name and their own share of the evidence — *Betacoronavirus pandemicum* with SARS-CoV-2 and SARS-CoV beside each other.

Look hardest at the species with the most interactions: a wrong call there moves the most evidence.

### 3. Group

**Default: collapse to the deepest node every taxon of the species shares.** Take each taxon's path below the species, outermost first, and keep the common prefix across all the species' taxa; the group is its last node, or the species itself when there is none. That is usually the node with the familiar name — `10407 Hepatitis B virus` under *Orthohepadnavirus hominoidei*. The default depends on which taxa the export holds, so check it again whenever the export changes.

**Overrides, checked on the path below the species before the default:**

- **Split nodes**: a taxon under one of these nodes groups at that node.

  | node      | virus      |
  | --------- | ---------- |
  | `2697049` | SARS-CoV-2 |
  | `694009`  | SARS-CoV   |
  | `11053`   | DENV-1     |
  | `11060`   | DENV-2     |
  | `11069`   | DENV-3     |
  | `11070`   | DENV-4     |
  | `39054`   | EV-A71     |
  | `42769`   | CV-A10     |
  | `31704`   | CV-A16     |
  | `12072`   | CVB3       |

- **Papillomaviridae split at rank `serotype`**: HPV16, HPV18, … are the viruses. No other family is split by rank.

Everything else stays whole, including the calls NAMING.md flags as worth revisiting: `IAV` as one virus, and HCV genotypes pooled.

### 4. Name

`full_name` is the group node's NCBI scientific name, first letter capitalized. `name` is the first of:

1. **A hand-chosen name**, from the table below.
2. **An NCBI `acronym` or `genbank acronym` of the group node**, the first with no space and at most 12 characters.
3. **`HPV<n>`** when the scientific name reads *human papillomavirus (type) n*.
4. **The VMR abbreviation of the species**, the first of a `;`-separated list.
5. **The scientific name**, when nothing above gives one. About two dozen tail rows end here; leave them.

Hand-chosen names — the familiar names acronyms get wrong, then the clashes resolved in NAMING.md:

| taxon     | name         | taxon     | name     |
| --------- | ------------ | --------- | -------- |
| `2697049` | `SARS-CoV-2` | `11709`   | `HIV-2`  |
| `694009`  | `SARS-CoV`   | `11234`   | `MeV`    |
| `11320`   | `IAV`        | `11908`   | `HTLV-1` |
| `10376`   | `EBV`        | `11909`   | `HTLV-2` |
| `10359`   | `HCMV`       | `11624`   | `LCMV`   |
| `37296`   | `KSHV`       | `11622`   | `LASV`   |
| `10298`   | `HSV-1`      | `1570291` | `EBOV`   |
| `10310`   | `HSV-2`      | `10245`   | `VACV`   |
| `10335`   | `VZV`        | `11292`   | `RABV`   |
| `10407`   | `HBV`        | `1678143` | `HEV`    |
| `3052230` | `HCV`        | `10255`   | `VARV`   |
| `11676`   | `HIV-1`      | `3052505` | `MARV`   |
| `64320`   | `ZIKV`       | `2169991` | `JUNV`   |
| `11060`   | `DENV-2`     | `39054`   | `EV-A71` |
| `11053`   | `DENV-1`     | `42769`   | `CV-A10` |
| `11069`   | `DENV-3`     | `31704`   | `CV-A16` |
| `11070`   | `DENV-4`     | `12072`   | `CVB3`   |
| `138949`  | `EV-B`       | `763552`  | `MmuPV1` |
| `10272`   | `RFV`        | `10568`   | `MmiPV1` |
| `10599`   | `HPV5b`      | `11723`   | `SIV`    |
| `57667`   | `SHIV`       | `176652`  | `IIV-6`  |
| `12721`   | `HIV`        | `207343`  | `BFoV`   |
| `11020`   | `BFV`        | `11276`   | `VSV`    |

### 5. Resolve clashes

Names must be unique; the build rejects a list where two rows share one. List every name held by more than one row, and resolve each by hand: the virus the literature most means by the abbreviation keeps it, the other gets a distinct one. Add the decision to the table above and to NAMING.md.

### 6. Write and check

Write one row per group, sorted by interactions descending:

| column           | read by the build | notes                                   |
| ---------------- | ----------------- | --------------------------------------- |
| `taxon_id`       | yes               | the group node                          |
| `name`           | yes               | step 4                                  |
| `full_name`      | yes               | step 4                                  |
| `family`         | no                | NCBI family's scientific name, or empty |
| `n_proteins`     | no                | distinct viral proteins of the export   |
| `n_interactions` | no                | interactions of the export, for review  |

Then build (`uv run bpgraph-build <run directory>`). The gate must pass, and the load reports two things to read before accepting the list: viral names within one virus differing only in case, and grouped proteins whose members differ in length by more than half — a sign a group pooled more than one chain.

Record in NAMING.md any rule that changed, with why.
