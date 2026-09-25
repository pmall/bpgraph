# Curated viruses — the naming and grouping choices

[`viruses.tsv`](viruses.tsv) names the viruses this graph groups viral proteins by. One row is one virus: the NCBI taxon that defines it, the familiar short name everyone uses, and the full name. [`PROCESS.md`](PROCESS.md) is how the list is produced, step by step.

| column      | notes                                                  |
| ----------- | ------------------------------------------------------ |
| `taxon_id`  | the NCBI taxon the group is anchored at                |
| `name`      | the familiar short name — `HBV`, `SARS-CoV-2`, `HPV16` |
| `full_name` | the scientific name of that taxon                      |

The build reads those three. `family`, `n_proteins` and `n_interactions` follow them for review only: the NCBI family, and how much of the export the row held when it was generated.

A viral protein resolves to the **most specific** row enclosing its own taxon, so strains, isolates and lab passages roll up to the virus they belong to without being listed here. Row order carries no meaning.

## Why this list exists at all

NCBI attaches a UniProt entry to whatever organism the entry names, which is almost always a strain — *Hepatitis B virus adw2/Rutter/1979*, *Influenza A virus (A/Puerto Rico/8/1934(H1N1))*. Evidence counted per strain is evidence scattered across accessions that are the same protein to anyone reading the literature.

Rolling up to NCBI's own species does not fix it either. The current ICTV binomials — *Orthohepadnavirus hominoidei*, *Lentivirus humimdef1*, *Betacoronavirus pandemicum* — sit above the familiar names, carry no acronym, and sometimes merge viruses nobody would pool: *Betacoronavirus pandemicum* holds both SARS-CoV-2 and SARS-CoV.

So the level is curated here rather than taken from a rank.

## How a group was chosen

**The default is the most specific taxon that still covers an entire species.** That is the node carrying the familiar name, and the node UniProt usually attaches to. *Orthohepadnavirus hominoidei* collapses to `10407 Hepatitis B virus`, so the row reads `HBV` rather than the binomial.

**Species holding several conventionally distinct viruses are split**, because a virologist names them apart and their evidence should not pool:

| species                             | split into                     |
| ----------------------------------- | ------------------------------ |
| *Betacoronavirus pandemicum*        | SARS-CoV-2, SARS-CoV           |
| *Orthoflavivirus denguei*           | DENV-1, DENV-2, DENV-3, DENV-4 |
| *Alpha-* and *Betapapillomavirus N* | HPV16, HPV18, HPV31, …         |
| *Enterovirus alphacoxsackie*        | EV-A71, CV-A10, CV-A16         |
| *Enterovirus betacoxsackie*         | CVB3                           |

The papillomaviruses split at NCBI's `serotype` rank, which for that family *is* the conventional type. Nowhere else is a rank used to decide.

**Everything else is left whole**, and these are the calls worth revisiting:

- **Influenza A is one virus, `IAV`.** Subtypes are reassortants of one virus, and the curated protein names — NS1, NP, PB1 — are given at the influenza A level, not per subtype. Splitting by subtype would scatter the evidence across H1N1, H5N1, H3N2 and the rest. This is the largest single choice in the list and the easiest to reverse.
- **HCV is one virus.** Genotypes behave as strains here, and a sizeable share of the interactions are attached above any genotype node, so splitting would strand them in a group of their own.
- **HBV, HIV-1, HSV-1, EBV, HCMV, KSHV, vaccinia, rabies, HEV and Marburg are one virus each.** What sits beneath them is strains and lab isolates.

## Where the names come from

In order: NCBI's own acronym for the group taxon, then the ICTV Virus Metadata Resource abbreviation for its species, then the scientific name.

A handful were decided by hand, because two unrelated viruses genuinely share an abbreviation in the literature and only one row can hold it:

| taxon    | name     | instead of | why                                          |
| -------- | -------- | ---------- | -------------------------------------------- |
| `11033`  | `SFV`    |            | Semliki Forest virus keeps it                |
| `10272`  | `RFV`    | SFV        | Shope/rabbit fibroma virus yields            |
| `11723`  | `SIV`    | CIV        | simian immunodeficiency virus                |
| `176652` | `IIV-6`  | CIV        | invertebrate iridescent virus 6 yields       |
| `57667`  | `SHIV`   | HIV        | simian-human immunodeficiency virus          |
| `12721`  | `HIV`    |            | unclassified HIV keeps the bare acronym      |
| `11020`  | `BFV`    |            | Barmah Forest virus keeps it                 |
| `207343` | `BFoV`   | BFV        | bovine foamy virus yields                    |
| `138949` | `EV-B`   | CVB3       | the enterovirus B catch-all, not CVB3 itself |
| `10599`  | `HPV5b`  | HPV5       | distinct from HPV5                           |
| `763552` | `MmuPV1` | McPV2      | *Mus musculus* papillomavirus 1              |
| `10568`  | `MmiPV1` | McPV2      | *Micromys minutus* papillomavirus 1          |

Roughly two dozen rows in the tail — obscure entries, and genuinely unnamed ones such as *Rotavirus sp.* — have no abbreviation anywhere and keep their scientific name in `name`.

## Protein names are case-sensitive

Nothing here folds case, and nothing downstream may either. EBV carries `BARF1`, a secreted protein, alongside `BaRF1`, the ribonucleotide reductase small subunit — and `BCRF1` alongside `BcRF1`. They are different genes that differ only in case. Folding them would merge two proteins into one and pool evidence that belongs apart.
