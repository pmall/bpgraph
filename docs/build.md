# bpgraph — build and validation

The graph is rebuilt, never updated. A run gathers every source into one directory — the curation database's export, and what is fetched for each silo — and builds a fresh graph and fresh vaults from it. See [`schema.md`](schema.md) for what is written, and [`roadmap.md`](roadmap.md) for why the sources are split into silos.

```
1. index       ->  bpgraph_staging          indexes only, before any data
2. build       ->  bpgraph_staging          CREATE in bulk
3. constrain   ->  bpgraph_staging          unique constraints
4. validate    ->  CALL db.constraints()    every row must be OPERATIONAL
5. swap        ->  RENAME bpgraph_staging bpgraph
```

Indexes come **first** so that every `MATCH` a load performs — and each relationship write is a key lookup — is index-backed. Constraints come **last**, because that is what makes them a gate rather than a write-time cost. A range index may precede its constraint; the reverse is an error, since creating a unique constraint also creates the index it needs.

`bpgraph.build.build()` runs all five; `uv run bpgraph-build <run directory>` loads a run and calls it, writes the sequence vaults into the run's `vault/`, then prints the counts and the dataset releases the run was fetched from.

Before step 1, loading has its own gates:

- **Every viral taxon must belong to a curated virus** in [`curation/viruses.tsv`](../curation/viruses.tsv). A taxon no row encloses fails the load, naming the taxa to add; nothing falls back to an NCBI rank.
- **Every detection method must have a class** in [`curation/methods.tsv`](../curation/methods.tsv). A PSI-MI term no row encloses, or that two rows disagree on, fails the load naming it. `uv run bpgraph-methods <run directory>` checks the curation against a run before a build.
- **Every cited pmid must have metadata** from `bpgraph-pubmed`.

`RENAME` overwrites its destination, so step 5 is the whole deployment. Old graphs are not kept. Staging exists so a bad export cannot land on the live graph — not for uptime.

## The run directory

A run is one directory under `data/`, gitignored. What every silo shares sits at the top; each silo has a directory of its own, holding what was fetched for it alone:

```
data/2026-09-09/
  export/              descriptions.tsv, peptides.tsv — what the curation database exported
  sources.tsv          which release of each dataset was fetched
  taxdmp.zip           taxonomy.sqlite          NCBI taxonomy
  psi-mi.obo                                    PSI-MI, for method names and classes
  go-basic.obo                                  the GO ontology
  hosts/9606/          the human silo
    swissprot.tsv      sequences.tsv            every reviewed human entry
    intact.tsv                                  IntAct, experimental and PubMed-cited
    goa.gaf.gz         go_annotations.tsv       experimental GO, one row per pmid
    publications.tsv                            PubMed, for every pmid the silo cites
  viral/               the viral silo
    functions.tsv      entries.tsv              UniProt text per span, sequence per entry
    publications.tsv
  topics/              ferroptosis.tsv          curated lists, resolved by hand
  vault/               host-9606.sqlite, viral.sqlite — written by the build
```

The export's `hh` rows are our curation of the human interactome, and belong to the human silo; its `vh` rows are the viral silo. Its format is [`export.md`](export.md).

Fetch in this order — each step reads what the one before wrote — then build:

```sh
uv run bpgraph-taxonomy data/2026-09-09     # NCBI taxonomy
uv run bpgraph-psimi data/2026-09-09        # PSI-MI
uv run bpgraph-swissprot data/2026-09-09    # hosts/9606: Swiss-Prot and sequences
uv run bpgraph-intact data/2026-09-09       # hosts/9606: IntAct, about 7 minutes
uv run bpgraph-go data/2026-09-09           # GO, and hosts/9606: experimental annotations
uv run bpgraph-functions data/2026-09-09    # viral: UniProt text and sequences
uv run bpgraph-pubmed data/2026-09-09       # both silos: PubMed metadata
uv run bpgraph-methods data/2026-09-09      # check every method has a class
uv run bpgraph-build data/2026-09-09        # the graph and the vaults
```

Every fetch records its dataset in `sources.tsv`, prefixed by its silo: the URL, the day it was fetched, and the release the source names — UniProt's `X-UniProt-Release`, IntAct's dated release, the ontology's `data-version`, GOA's `date-generated`, PubMed's `DbBuild`. `bpgraph-build` prints them after the counts. Each silo fetches its own publications, so a pmid two silos cite is fetched twice; `bpgraph-pubmed` only fetches pmids its silo's file lacks, so a rerun is cheap.

## Loading

Each silo is loaded on its own, then joined:

- **Human.** Every Swiss-Prot entry is a protein. IntAct's rows are descriptions, and our curated `hh` rows merge onto them: a row with the same pair, pmid and method class as an IntAct description adds its `stable_id` to it; one IntAct lacks is a description of its own. The load logs how many curated rows IntAct already had, and how many pairs only we have. A curated row naming an accession not in Swiss-Prot, or coded `MI:0000`, is dropped and logged.
- **Viral.** Our `vh` rows, their viral partners grouped into curated proteins. The human partner must be a Swiss-Prot entry; a row whose partner is not is dropped and logged.
- **Joined.** Methods, named from PSI-MI and classed from the curation; the publications something cites; the GO terms the annotations reach, with their ancestor closure; the topics; the peptides, placed by the silo their curated row belongs to.

## Stages within step 2

1. **Proteins, taxonomy, topics** — the entity backbone, with `:IN_TAXON`.
2. **Publications** — and `:FUNCTION_CITES` onto them.
3. **Interactions** — `:Interaction`, `:Description`, `:Method`, `:Peptide`.
4. **GO** — `:GoTerm` nodes with the ancestor closure, and the `:Annotation` nodes.
5. **Derive** — the `:Interaction` counters. The `:INTERACTS_WITH` shortcut [`schema.md`](schema.md) describes would go here; it is not built.

## Writing

Nothing pre-exists in a fresh graph, so `MERGE` buys nothing and costs a lookup per row. Deduplicate in Python — the run is a full snapshot, so every distinct protein, publication, method and peptide is known before the first write — then write in batches.

```cypher
UNWIND $rows AS r
CREATE (:Protein:Human {id: r.id, name: r.name,
                        description: r.description, function: r.function})
```

`GraphWriter.create` writes that clause itself, from the keys of the rows it is given, so a node's properties and the record behind them are one list rather than two that can drift.

Nodes first, then relationships by key lookup:

```cypher
UNWIND $rows AS r
MATCH (a:Protein {id: r.a}), (b:Protein {id: r.b})
CREATE (a)<-[:INVOLVES {side: 'a'}]-(:Interaction:VH {id: r.id})-[:INVOLVES {side: 'b'}]->(b)
```

Never interpolate values into Cypher — pass parameters.

## Constraints are the validation gate

Creating a unique constraint over rows that already violate it does not error. The constraint ends up in state `FAILED`, which `CALL db.constraints()` reports:

```
type    label    properties  entitytype  status
UNIQUE  Protein  [id]        NODE        FAILED
```

Step 4 is therefore a hard gate: `FAILED` means the snapshot violated a key, and the staging graph is dropped rather than swapped in.

**Wait it out first.** A constraint is applied asynchronously, and reports `PENDING` and then `UNDER CONSTRUCTION` while it scans — on a graph this size, for several seconds. Neither is a verdict, and reading one as a failure fails a sound export; `validate_constraints` polls until every row has settled on `OPERATIONAL` or `FAILED`.

The gate covers what deduplication cannot see. `bpgraph.dedupe` collapses records that repeat identically and raises `ConflictingRecords` when two share a key and disagree; whatever slips past lands on a constraint.

## Counters

`Interaction.n_descriptions` / `n_publications` / `n_methods` / `n_peptides` are computed in one pass at the end of the build, not maintained. `n_methods` counts method classes.

## Auditing what was built

The constraint gate proves keys are unique and nothing else, so `uv run bpgraph-audit` reads the live graph and checks it against every other promise in [`schema.md`](schema.md): properties present and correctly typed, no property the schema does not list, one of `:Human`/`:Viral`, `:HH`/`:VH` and `:Virus`/`:Family`, derived ids agreeing with the values behind them, every edge joining the labels it is declared to join, a description being IntAct's or one curated row's, an annotation's evidence being experimental, slot `a` holding the human protein, the counters equalling what they count, no publication or peptide left with nothing pointing at it. Each check is one read-only query returning the rows that break its rule, so an empty result is a pass; the command exits non-zero when anything fails and prints a few offenders per failure.

Run it after a build, and after anything that touches the writers. It takes about as long as a build.

`bpgraph.audit` restates those rules by hand rather than deriving them from the models or the writers — code checked against itself always agrees. Changing the schema means changing `schema.md`, the writers, **and** the audit, and the audit failing is what tells you one of the three was missed.

## What the load reports

Some things are worth a human's look without being wrong enough to stop a build. The load logs them:

- **How our HH curation sits on IntAct**: curated rows IntAct already has, those it lacks, and the pairs only we have.
- **Curated rows dropped**: coded `MI:0000`, or naming an accession no longer in Swiss-Prot.
- **Viral names within one virus that differ only in case.** Names are case-sensitive, and EBV's `BARF1` / `BaRF1` and `BCRF1` / `BcRF1` are genuinely different proteins; any new pair may be a typo.
- **Grouped viral proteins whose members differ in length by more than half** — HBV `HBsAg` over its S/M/L forms, or a fragment. Such members may not be one chain, and may not share one function text.
- **Proteins whose entries carry different function text.** The protein keeps the commonest, weighted by descriptions.
