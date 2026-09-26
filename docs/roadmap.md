# bpgraph — roadmap

Where the graph is going, and why it is shaped the way it is. [`schema.md`](schema.md) is what the graph holds today; this document is what it is meant to become, and the order of the steps.

## The vision

bpgraph is a knowledge graph of protein–protein interactions built for an agent to explore. Its value is the text around each fact: every interaction is backed by the publications that report it, every annotation by the publication that shows it, and every protein carries its curated description. An agent reads that connected text and makes connections a person would need years of reading to make.

The long-term scope is **One Health**: the interactomes of many host species, not only human, with viral proteins probing them. Research on one host informs the others.

## Three tiers of ingestion

### Tier 1 — hosts

Each host species is ingested on its own, as a **silo**: its own downloads, its own metadata, its own publications. Adding a host touches no other host. Within a host, only **experimentally validated** facts come in, because an experiment is what gives a fact a publication, and a publication is what gives an agent something to read.

1. **Interactions**, from IntAct: experimental detection methods, PubMed-cited, between reviewed proteins of that host. For human, our own HH curation is merged on top of IntAct; how much it adds beyond IntAct is measured, not assumed.
2. **GO annotations** with experimental evidence codes (`EXP`, `IDA`, `IPI`, `IMP`, `IGI`, `IEP` and the high-throughput `HTP`, `HDA`, `HMP`, `HGI`, `HEP`), each citing a PubMed id. Electronic and inferred annotations are left out: they add no publication, and they restate what other annotations say.
3. **UniProt annotations of the proteins**, Swiss-Prot wherever a host has it: name, description, function text, and the publications UniProt cites for them.
4. **Publication metadata** for every pmid the three above cite: title, abstract, journal, authors, year — fetched from PubMed.
5. **The vaults** *(later, except sequences)*. A relational database beside the graph, keyed by pmid for full text and by accession for sequences. Kept out of the graph on purpose:
   - technically, so the graph stays small enough to traverse;
   - methodologically, so they are never the basis of large-scale reasoning, only of deep verification of a hypothesis the graph produced.
6. **ESM-C sparse autoencoder annotations** *(later)*. Features of a protein language model's sparse autoencoder, computed on host protein sequences from the vault. They add a layer of AI predictions that connects proteins within a host, and, more importantly, **across hosts**. They are the only link between host silos: two hosts share no node except through them.

### Tier 2 — viral probes

Our curated virus–host interactions. A viral protein is a probe into a host interactome: today into human only, later possibly into others. Tier 2 brings the viral proteins with their UniProt annotations and the publications behind them, the publications supporting the interactions, and the mature viral sequences into the sequence vault. Its metadata is fetched as its own set, apart from any host's.

### Tier 3 — special metadata

What we curate by hand and hand over as-is: **peptides** reported sufficient for an interaction, and **topics**, curated lists of host proteins such as ferroptosis.

## Principles that follow

- **A host is a silo.** Its downloads live in their own directory of a run, its publications are fetched for it alone, and its build stage reads nothing from another host. A publication cited by two silos is one node in the graph, but each silo fetches it.
- **Only what an experiment backs.** Every fact in the graph that is not curated by us points at a publication.
- **The graph holds what an agent reasons over; the vaults hold what it verifies against.** Sequences and full text never enter the graph.
- **UniProt entries are not nodes.** An entry node carried two things: which strain a viral protein was seen on, and where its mature chain sits. Both are about sequences, and belong in the sequence vault. A host protein is one accession, which is already its id; a viral protein's accessions and spans are rows in the vault, which is what retrieving every mature sequence of a protein needs. Adding a host then adds proteins, not proteins and entries.

## Beyond ingestion: splitting the repository

Consumers of the graph — the analysis skills and the reports — will move to repositories of their own, so that each has its own instructions. This repository keeps the ingestion and the servers:

- an **internal query API**, not exposed, defining the queries consumers run: today's skill scripts, and more;
- the **MCP server**, the only thing exposed, serving that API and read-only Cypher to consumers.

Queries written now go through `bpgraph.query` so they can move behind that API unchanged.

## Order of work

| step | what                                                                      | status |
| ---- | ------------------------------------------------------------------------- | ------ |
| 1    | Human host: IntAct + our HH, experimental GO, Swiss-Prot, PubMed          | done   |
| 2    | Viral probes: our VH, viral UniProt text, PubMed, as their own silo       | done   |
| 3    | Peptides and topics                                                       | done   |
| 4    | Sequence vault in SQLite: host sequences, viral entries and mature spans  | done   |
| 5    | Drop `:Entry` from the graph                                              | done   |
| 6    | Full-text vault, keyed by pmid                                            | later  |
| 7    | ESM-C SAE features on host sequences, intra-host                          | later  |
| 8    | A second host: labels move from `:Human` to a host label with its species | later  |
| 9    | SAE features as the cross-host link                                       | later  |
| 10   | Internal query API; MCP serves it; consumers move out                     | later  |

Steps 1–5 are one build, described in [`build.md`](build.md); they replaced a pipeline that took everything from the curation export.

Known gaps in what is done:

- About one viral entry in six has no sequence in the vault: UniProt no longer returns it. The export will carry the curated viral sequences, which the vault will take instead of fetching them.
- Only human is a host. `:Human`, `:HH` and the `9606` of the run layout are the places a second host touches (step 8).
