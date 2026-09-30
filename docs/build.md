# bpgraph — build and validation

The graph is rebuilt, never updated. A run gathers every source into one directory — the curation database's export, and what is fetched for each silo — and builds a fresh graph and fresh vaults from it. See [`schema.md`](schema.md) for what is written, and [`roadmap.md`](roadmap.md) for why the sources are split into silos.

**Everything streams.** No step, fetch or build, holds a whole file in memory. A file is read a line at a time; where rows of two files have to meet — a curated row and the IntAct row it merges onto, a peptide and its description — both are written to an intermediate file keyed by what they share, sorted on disk with GNU `sort`, and read side by side, so memory holds one group of rows sharing a key (`bpgraph.files`). The graph is written in batches of 1,000 rows. The only thing held whole is PSI-MI with the curated keep flags, some 1,700 terms of reference data.

## The run directory

A run is one directory under `data/`, gitignored. What every silo shares sits at the top; each silo has a directory of its own, holding what was fetched for it alone. A fetch keeps exactly what the build reads — a raw dump is streamed, or deleted once it is read:

```
data/2026-09-09/
  export/              descriptions_hh.tsv, descriptions_vh.tsv, viral_proteins.tsv,
                       peptides.tsv — what the curation database exported
  sources.tsv          which release of each dataset was fetched
  taxonomy.sqlite      NCBI taxonomy, a parent per taxon
  psi-mi.obo           PSI-MI, for method names and the detection methods to flag
  hosts/9606/          the human silo
    swissprot.tsv      every reviewed human entry: name, description, function
    sequences.tsv      their sequences, for the vault
    intact.tsv         IntAct's descriptions the graph takes
    go_annotations.tsv experimental GO annotations, one row per pmid
    go_terms.tsv       the GO terms they reach, ancestors included
    go_edges.tsv       the is_a and part_of edges between those terms
    publications.tsv   PubMed, for every pmid the silo cites
  viral/               the viral silo
    functions.tsv      UniProt function texts per entry and span, one row each
    entries.tsv        UniProt protein name per entry
    publications.tsv   PubMed, for every pmid the silo cites
  vault/               host-9606.sqlite, viral.sqlite — written by the build
```

The export's `descriptions_hh.tsv` is our curation of the human interactome, and belongs to the human silo; `descriptions_vh.tsv` and `viral_proteins.tsv` are the viral silo. Its format is [`export.md`](export.md). The build writes its intermediate files into `build/` while it runs, and removes it when it ends.

## Fetching

Each step reads what the ones before it wrote:

```sh
uv run bpgraph-taxonomy data/2026-09-09     # NCBI taxonomy
uv run bpgraph-psimi data/2026-09-09        # PSI-MI
uv run bpgraph-methods data/2026-09-09      # check every detection method has a row
uv run bpgraph-swissprot data/2026-09-09    # hosts/9606: Swiss-Prot and sequences
uv run bpgraph-intact data/2026-09-09       # hosts/9606: IntAct, by curation/methods.tsv
uv run bpgraph-go data/2026-09-09           # hosts/9606: functional GO annotations, terms, edges
uv run bpgraph-functions data/2026-09-09    # viral: UniProt text and protein names
uv run bpgraph-pubmed data/2026-09-09       # both silos: PubMed metadata
uv run bpgraph-build data/2026-09-09        # the graph and the vaults
```

- **Taxonomy.** NCBI's `taxdmp.zip`, loaded into SQLite row by row with each taxon's parent; the zip is deleted once loaded. A taxon's ancestors are a walk up its parents.
- **Swiss-Prot.** Every reviewed entry of the host, fetched a page of 500 at a time. The graph's human proteins, and the set IntAct, GO and our curation are cut to. Swiss-Prot is for the host only: viral proteins come from UniProtKB as a whole, reviewed or not.
- **IntAct.** The host's MITAB zip, over a gigabyte, inflated as it arrives. A row is kept when it reports a real interaction, observed by an experiment, in a publication: both partners are Swiss-Prot entries, it cites one pmid, it is not negative, and its detection method is flagged `keep` in [`curation/methods.tsv`](../curation/methods.tsv). A detection method with no row there fails the fetch. A publication that re-reports an experiment, grouped in [`curation/publications.tsv`](../curation/publications.tsv), keeps only the pairs no lower pmid of its group reports: BioPlex 3.0 adds to BioPlex 2.0 only what 2.0 lacks. Whether both partners are Swiss-Prot entries is two sorted merges against `swissprot.tsv`.
- **GO.** The ontology and the host's GOA file, both streamed. GOA is cut to experimental annotations citing PubMed, on current terms and Swiss-Prot entries, and to function: no `cellular_component` term, and nothing at or below `protein binding`, the subtree found by walking the ontology's edges downward; then the closure above the annotated terms is walked one level at a time on disk, and the silo keeps the annotations, the terms reached and the edges walked.
- **Viral UniProt.** The export's viral entries and spans, sorted by accession and fetched a hundred accessions at a time: the function text UniProt gives each span, and each entry's protein name. An entry UniProt has retired gets neither.
- **PubMed.** Every pmid a silo cites, compared as a sorted file with the silo's `publications.tsv`: a pmid already there keeps its row, one missing is fetched, one nothing cites any more is dropped. It is the one slow fetch, and a rerun only fetches what is new.

Every fetch records its dataset in `sources.tsv`, prefixed by its silo: the URL, the day it was fetched, and the release the source names — UniProt's `X-UniProt-Release`, IntAct's dated release, the ontology's `data-version`, GOA's `date-generated`, PubMed's `DbBuild`, the taxonomy's `Last-Modified`. `bpgraph-build` prints them after the counts.

## The build, in order

`uv run bpgraph-build data/2026-09-09` runs these steps in this order. Steps 1 to 7 only read the run and write files in `build/`: every error a run can hold fails there, with its file and line, before the graph is touched.

01. **Curated rows.** Both description files are read into one file of curated rows. A `stable_id` must be unique across the two; every viral taxon must have a curated virus, or the build fails naming them. A row whose human partner is not a Swiss-Prot entry is dropped — a sorted merge against `swissprot.tsv`, per partner — with the accessions logged. A dropped row stays in the file, marked, so its peptides go with it.
02. **Viral sites.** Each VH row's viral partner is placed: its taxon made current, its curated virus found, its protein id made from the virus and the name. Every viral partner must be a row of `viral_proteins.tsv` under the same name and taxon. Each entry and span a kept row observes is a site, with its sequence.
03. **HH descriptions.** IntAct's rows and our kept HH rows go into one file keyed by pair and pmid, IntAct first and in IntAct order within a key, and are sorted. Each key's rows arrive together: a curated row joins the IntAct description with the lowest IntAct id, and is a description of its own when IntAct has none. The load logs how many curated rows IntAct already had.
04. **VH descriptions.** Each kept VH row is a description of its own, and the vault notes which entry it observed.
05. **Viral proteins.** Each site takes its UniProt function text and its entry's UniProt name; the sites of each protein are then read together. A protein's members are one chain by definition, so they should agree: a protein keeps every distinct text they carry, and those carrying more than one are logged for curation.
06. **Peptides.** Each peptide finds its curated row, must name one of that row's partners as its source, and goes to the description the row became. A peptide on no row fails the build; one on a dropped row is dropped with it.
07. **Publications.** Every pmid the graph cites — descriptions, GO annotations, function text — is looked up in the silos' `publications.tsv`, host first. A cited pmid no silo has fails the build: run `bpgraph-pubmed`.
08. **Staging.** `bpgraph_staging` is emptied and its indexes created, before any data, so every `MATCH` a write performs is an index lookup.
09. **Writing**, from the files of steps 1 to 7, in dependency order:
    1. proteins, human then viral;
    2. viruses, their families, `:PARENT` and `:IN_TAXON`;
    3. publications, and `:FUNCTION_CITES` onto them;
    4. peptides;
    5. interactions: descriptions and peptide reports sorted by interaction are read side by side, and each interaction is written once, with its counters counted from its group, its two `:INVOLVES`, its `:INTERACTS_WITH` shortcut, its descriptions and their `:REPORTS`;
    6. GO terms, their edges, and the annotations.
10. **Gate.** The unique constraints are created and every one must settle on `OPERATIONAL`; one `FAILED` means a duplicate key, and staging is dropped.
11. **Swap.** `RENAME bpgraph_staging bpgraph`. It overwrites its destination, so this is the whole deployment; old graphs are not kept. Staging exists so a bad export cannot land on the live graph — not for uptime.
12. **Vaults.** `host-9606.sqlite` from `sequences.tsv`; `viral.sqlite` from the viral sites, their entries and the VH observations. Each is written beside where it goes, then moved there.
13. **Cleanup.** `build/` is removed, whether the build succeeded or not.

## Writing

Nothing pre-exists in a fresh graph, so every write is a `CREATE`: `MERGE` would buy nothing and cost a lookup per row. The preparation has already made every row distinct, so a node is written once.

```cypher
UNWIND $rows AS r
CREATE (:Protein:Human {id: r.id, name: r.name,
                        description: r.description, function: r.function})
RETURN count(*)
```

`GraphWriter.create` writes that clause itself, from the keys of the rows it is given, so a node's properties and the record behind them are one list rather than two that can drift. Relationships are written by key lookup:

```cypher
UNWIND $rows AS r
MATCH (a:Protein {id: r.side_a})
MATCH (b:Protein {id: r.side_b})
CREATE (a)<-[:INVOLVES {side: 'a'}]-(:Interaction:VH {id: r.id, n_descriptions: r.n_descriptions, …})-[:INVOLVES {side: 'b'}]->(b)
CREATE (a)-[:INTERACTS_WITH {interaction_id: r.id, n_descriptions: r.n_descriptions, …}]->(b)
RETURN count(*)
```

Every statement returns how many rows came through, and a batch where some matched nothing raises `UnmatchedRows`: the preparation guarantees every endpoint exists, so a row lost there is a bug, never data. Never interpolate values into Cypher — pass parameters.

## Constraints are the validation gate

Creating a unique constraint over rows that already violate it does not error. The constraint ends up in state `FAILED`, which `CALL db.constraints()` reports:

```
type    label    properties  entitytype  status
UNIQUE  Protein  [id]        NODE        FAILED
```

Step 10 is therefore a hard gate: `FAILED` means the run violated a key, and the staging graph is dropped rather than swapped in.

**Wait it out first.** A constraint is applied asynchronously, and reports `PENDING` and then `UNDER CONSTRUCTION` while it scans — on a graph this size, for several seconds. Neither is a verdict, and reading one as a failure fails a sound export; `validate_constraints` polls until every row has settled on `OPERATIONAL` or `FAILED`.

## Counters

`Interaction.n_descriptions` / `n_publications` / `n_peptides` are counted while the interaction is written, from the group of its descriptions and peptides: descriptions, distinct pmids, distinct peptide sequences. The `:INTERACTS_WITH` edge is written in the same statement and carries the same three.

## Auditing what was built

The constraint gate proves keys are unique and nothing else, so `uv run bpgraph-audit` reads the live graph and checks it against every other promise in [`schema.md`](schema.md): properties present and correctly typed, no property the schema does not list, one of `:Human`/`:Viral`, `:HH`/`:VH` and `:Virus`/`:Family`, derived ids agreeing with the values behind them, every edge joining the labels it is declared to join, a description being IntAct's or one curated row's, an IntAct description carrying a method [`curation/methods.tsv`](../curation/methods.tsv) keeps, no interaction holding IntAct descriptions from two publications of one group of [`curation/publications.tsv`](../curation/publications.tsv), an annotation's evidence being experimental and its term a process or a function outside `protein binding`, slot `a` holding the human protein, the counters and the shortcut equalling what they count, no publication or peptide left with nothing pointing at it. Each check is one read-only query returning the rows that break its rule, so an empty result is a pass; the command exits non-zero when anything fails and prints a few offenders per failure. It takes under half a minute, so it runs after every build: a check counts a node's edges with `outdegree`, never a pattern comprehension, and never walks every path down the GO DAG.

Run it after a build, and after anything that touches the writers.

`bpgraph.audit` restates those rules by hand rather than deriving them from the loaders or the writers — code checked against itself always agrees. Changing the schema means changing `schema.md`, the writers, **and** the audit, and the audit failing is what tells you one of the three was missed.

## What the build reports

Some things are worth a human's look without being wrong enough to stop a build. The build logs them:

- **How our HH curation sits on IntAct**: curated rows IntAct already has, those it lacks, and the interactions only our curation reports.
- **Curated rows dropped**: naming an accession no longer in Swiss-Prot, with the accessions.
- **Viral proteins whose members disagree**: members carrying different sets of function texts, or different UniProt names. One entry holding a generic text beside a curated one is not a disagreement. The protein keeps every distinct text; the list is for curation to check that the members really are one chain.
- **Viral proteins whose members differ in length by more than half** — HBV `HBsAg` over its S/M/L forms, or a fragment.
- **Viral names within one virus that differ only in case.** Names are case-sensitive, and EBV's `BARF1` / `BaRF1` and `BCRF1` / `BcRF1` are genuinely different proteins; any new pair may be a typo.
