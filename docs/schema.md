# bpgraph — graph schema

FalkorDB is schemaless; **this document is the schema**. Nothing is written to the graph that is not described here. Graph key: `bpgraph`.

Companion documents, load when relevant: [`build.md`](build.md) (how a run builds and validates a graph), [`roadmap.md`](roadmap.md) (where the schema is going).

## Principles

1. **A graph, not tables.** An entity is keyed by its natural key, the value the world names it by. A node that links entities — an interaction, a description, an annotation — has no key of its own: it is what it links, and its uniqueness is checked by pattern (§3). No id is ever derived by joining values into a string.
2. **No optional properties.** Every property listed here is always present. Free text that is unknown is `''`, never null or absent.
3. **Labels carry the type, not properties.** Human vs viral, HH vs VH, virus vs family, curated vs IntAct are labels — no `kind` or `source` property duplicates them.
4. **Reify the n-ary facts.** An interaction observation links a pair, a publication and some peptides; a GO annotation links a protein, a term and publications. Cypher edges join exactly two nodes and cannot be an endpoint themselves, so those facts are nodes: `:Description` and `:Annotation`. What only qualifies one link is a property of that edge.
5. **Two levels of interaction.** `:Interaction` is the deduplicated claim ("A binds B"); `:Description` is one observation of it, in one publication, by one method.
6. **Every fact we did not curate points at a publication.** Interactions, GO annotations and function text come in only when a publication backs them, and the publication is a node an agent can read.
7. **Sequences only on `:Peptide`.** Peptides are the deliverable; every other sequence is in the sequence vaults beside the graph, never in it (§5).

______________________________________________________________________

## 1. Nodes

### `:Protein` + `:Human` | `:Viral`

What an interaction joins, and what an analysis means by a protein: `GPX4`, `NS5A` of HCV, `HBx` of HBV. Human or viral comes from `labels(p)`.

A **human** protein is one reviewed UniProt entry, keyed by its accession. **Every** Swiss-Prot human entry is a protein of the graph, whether or not an interaction names it: about 20,000, each with its function text and GO annotations.

| property      | type | notes                                                 |
| ------------- | ---- | ----------------------------------------------------- |
| `accession`   | str  | **key**, the Swiss-Prot accession                     |
| `name`        | str  | gene symbol, `GPX4`                                   |
| `description` | str  | UniProt protein name, e.g. `Glutathione peroxidase 4` |
| `function`    | str  | UniProt `CC FUNCTION` text                            |

A **viral** protein is a curated mature protein of a curated virus, whichever strains and accessions it was observed on: SARS-CoV-2 `nsp2` is one node, although curation saw it on pp1a, on pp1ab and on a TrEMBL copy, and HBV `HBx` is one node over twenty-one accessions. A name means nothing without its virus, so a viral protein is keyed by both. Which accessions, at which spans, and in which strains, is kept in the viral sequence vault (§5), not in the graph.

| property        | type | notes                                                          |
| --------------- | ---- | -------------------------------------------------------------- |
| `ncbi_taxon_id` | int  | **key**, with `name`: its curated virus's NCBI taxon id        |
| `name`          | str  | **key**, with `ncbi_taxon_id`: the curated mature-protein name |
| `function`      | str  | UniProt `CC FUNCTION` text — see below                         |

**Names are case-sensitive.** EBV carries `BARF1`, a secreted protein, beside `BaRF1`, the ribonucleotide reductase small subunit. Folding case would merge them.

**A viral protein keeps every function text its members carry.** Only reviewed entries give function text: an unreviewed entry's is automatic annotation citing no publication. UniProt text is per entry, and per chain where the entry scopes it; a viral protein on several entries has several. Curation groups one chain across strains, so they should agree — but they are worded by different curators, so none is picked: `function` holds each distinct text once, as paragraphs separated by a blank line. The build logs every protein carrying more than one, for curation to check the members really are one chain. The publications UniProt cites for the texts are `:FUNCTION_CITES` edges. A viral protein has no UniProt `description`: the name UniProt gives an entry is the entry's, a polyprotein's for most mature proteins, not the protein's.

### `:Taxon` + `:Virus` | `:Family`

Only the curated viruses a viral protein belongs to, and the family above each. Human proteins get no `:Taxon` node, and strains get none either: they are in the viral vault.

`:Virus` — one row of [`curation/viruses.tsv`](../curation/viruses.tsv), which [`curation/viruses.md`](../curation/viruses.md) explains. A viral protein belongs to the most specific row enclosing its entry's taxon.

| property        | type | notes                                              |
| --------------- | ---- | -------------------------------------------------- |
| `ncbi_taxon_id` | int  | **key**, the NCBI taxon the virus is anchored at   |
| `name`          | str  | familiar short name: `HBV`, `SARS-CoV-2`, `HPV16`  |
| `full_name`     | str  | scientific name of that taxon: `Hepatitis B virus` |

`:Family` — the NCBI family above a virus.

| property        | type | notes           |
| --------------- | ---- | --------------- |
| `ncbi_taxon_id` | int  | **key**         |
| `name`          | str  | scientific name |

The virus level is curated rather than an NCBI rank: NCBI attaches UniProt entries to strains, and its species sometimes pool viruses nobody would, *Betacoronavirus pandemicum* holding both SARS-CoV-2 and SARS-CoV. The `:PARENT` edge from a virus to its family is derived at build time from the NCBI taxonomy, which this repo keeps in SQLite (`bpgraph.taxonomy`). A virus with no family gets no edge: it stays queryable, it just falls out of family rollups.

### `:Publication`

A PubMed article, whatever cites it: a description, an annotation, a protein's function text, or several of them. Metadata comes from PubMed. A pmid PubMed does not return keeps its `pmid` alone: empty text, `year` 0.

| property   | type  | notes                                |
| ---------- | ----- | ------------------------------------ |
| `pmid`     | str   | **key**                              |
| `title`    | str   |                                      |
| `abstract` | str   |                                      |
| `journal`  | str   |                                      |
| `year`     | int   | `0` when PubMed does not give one    |
| `authors`  | [str] | `LastName Initials`, or a consortium |

### `:Interaction` + `:HH` | `:VH`

The deduplicated claim that two proteins interact, and nothing else: it is its two proteins, joined by two `:INVOLVES` edges, one interaction per pair. Because a viral protein pools its strains, so does the claim: every description of HBx binding a human protein supports one interaction, whichever HBV accession it was observed on. No provenance of its own — that hangs off `:Description`. The counters are the confidence signal; there is no score. `:HH` and `:VH` appear on no other label, so `MATCH (i:VH)` is unambiguous: a `:VH` joins a human protein and a viral one, an `:HH` two human proteins.

| property         | type | notes                                                         |
| ---------------- | ---- | ------------------------------------------------------------- |
| `n_descriptions` | int  | supporting descriptions                                       |
| `n_publications` | int  | **distinct** publications                                     |
| `n_methods`      | int  | **distinct** detection methods, by `method_id`                |
| `n_peptides`     | int  | distinct peptides; `> 0` answers "do we have a peptide here?" |

**A homodimer is an ordinary `:HH`** whose two `:INVOLVES` edges point at the same protein. Entering from a protein therefore reaches it twice, once per edge, so a query that ranks a protein's partners excludes it with `WHERE partner <> self` unless self-binding is what it is asking about.

### `:Description` + `:Curated` | `:IntAct`

One observation of an interaction: one pair, one publication, one method, and its peptides. Its method is two properties; everything else about it is its edges. Its type is its interaction's — `(d)-[:SUPPORTS]->(:VH)`.

A **`:Curated`** description is one row of our curation, keyed by its `stable_id`: one row, one description, however many rows link the same pair, publication and method — a paper testing several strains of a virus is one row per strain. Every VH description is curated.

An **`:IntAct`** description is IntAct's, of a publication we have not curated for HH interactions: we read such a publication and decided what it shows, so all IntAct could add is what we decided against. A publication we curated for VH rows only does not count, IntAct's records being human–human. IntAct records sharing a pair, a publication and a method are one description, which has no key.

| property      | type | notes                                                   |
| ------------- | ---- | ------------------------------------------------------- |
| `stable_id`   | str  | `:Curated` only, **key**: our curation's id for the row |
| `method_id`   | str  | PSI-MI id of the detection method, e.g. `MI:0018`       |
| `method_name` | str  | PSI-MI's name, e.g. `two hybrid`                        |

The method is a property because it joins nothing: a description has exactly one, and no query walks from a method to its descriptions. Two methods are two descriptions.

### `:Annotation`

What GO states about a human protein: that it has a function or takes part in a process — the term — as its qualifier says, shown by publications. One per protein, term and qualifier; it is a node because it joins a protein, a term and publications, and has no key: it is what it links.

| property    | type | notes                                                                                                                              |
| ----------- | ---- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `qualifier` | str  | how the protein relates to the term: `enables`, `involved_in`, `contributes_to`, `acts_upstream_of…`; `NOT\|…` states the opposite |

How each publication shows it is on its `:REPORTED_IN` edge: `evidence_codes`, the experimental codes GOA gives that publication for it. Which database recorded it is not kept. Electronic and inferred annotations are not loaded: they cite no publication.

**`NOT` is a finding, not an absence.** `NOT|involved_in` says a paper showed the protein does not take part in the process; such an annotation must never be read as the protein having the function.

**Function only.** Two parts of GO are not loaded. `cellular_component`, the whole namespace, because where a protein sits is not what it does, and much of it is proteomics listing everything a purified fraction held. And `protein binding` (`GO:0005515`) with every term below it — `identical protein binding`, `enzyme binding`, `ubiquitin protein ligase binding`… — because such an annotation says the protein binds another protein: an interaction, which `:Interaction` states better, naming the partner.

### `:Peptide`

A short subsequence reported sufficient for an interaction — the drug-discovery precursor, and the only place residues are stored. One node per sequence, which is its key: the same sequence seen in two proteins is one peptide.

| property   | type | notes   |
| ---------- | ---- | ------- |
| `sequence` | str  | **key** |
| `length`   | int  |         |

It is described by its edges: `:FROM` each protein it was cut from, `:BINDS` each protein it was shown to bind, and the curated descriptions that `:REPORTS` it. A homodimer's peptide binds its own source. Within one description, the peptide comes from the one of its two proteins it is `:FROM`, and binds the other; the build fails a description reporting a peptide from both.

### `:GoTerm`

| property    | type | notes                                       |
| ----------- | ---- | ------------------------------------------- |
| `go_id`     | str  | **key**, e.g. `GO:0097707`                  |
| `name`      | str  |                                             |
| `namespace` | str  | `biological_process` / `molecular_function` |

Annotated terms **plus their full ancestor closure**, so rolling up to a coarse process is a traversal, not a lookup table. Only the two namespace roots have no parent; every other term sits under one. A term GO retired is detached from the hierarchy and never annotated, so none is loaded; the build fails on an annotation to one. A query cuts to the namespace it wants — `biological_process` is the process axis, `molecular_function` the mechanistic one.

GO is the structured functional layer; `description` and `function` on `:Protein` say the same thing in prose. UniProt's smaller controlled vocabularies — keywords, InterPro/Pfam — would each follow this pattern if a query ever wants them. None are modelled until then.

**Only human proteins are annotated.** GOA annotates a whole accession, while a viral protein here is one mature chain of a polyprotein, and nothing in GOA says which chain a term belongs to.

______________________________________________________________________

## 2. Relationships

| pattern                                         | properties          | meaning                                      |
| ----------------------------------------------- | ------------------- | -------------------------------------------- |
| `(:Interaction)-[:INVOLVES]->(:Protein)`        | —                   | the two partners                             |
| `(:Description)-[:SUPPORTS]->(:Interaction)`    | —                   | observation → claim                          |
| `(:Description)-[:REPORTED_IN]->(:Publication)` | —                   |                                              |
| `(:Curated)-[:REPORTS]->(:Peptide)`             | —                   | a peptide the observation reported           |
| `(:Peptide)-[:FROM]->(:Protein)`                | —                   | a protein the peptide was cut from           |
| `(:Peptide)-[:BINDS]->(:Protein)`               | —                   | a protein the peptide was shown to bind      |
| `(:Annotation)-[:ANNOTATES]->(:Human)`          | —                   | the annotated protein                        |
| `(:Annotation)-[:OF_TERM]->(:GoTerm)`           | —                   | the term, the most specific that fits        |
| `(:Annotation)-[:REPORTED_IN]->(:Publication)`  | `evidence_codes`    | a publication showing it, and how            |
| `(:Protein)-[:FUNCTION_CITES]->(:Publication)`  | —                   | evidence UniProt cites for `function`        |
| `(:Viral)-[:IN_TAXON]->(:Virus)`                | —                   | the curated virus, of the protein's taxon id |
| `(:Virus)-[:PARENT]->(:Family)`                 | —                   | virus → family                               |
| `(:Protein)-[:INTERACTS_WITH]->(:Protein)`      | counters, see below | shortcut over an interaction                 |
| `(:GoTerm)-[:IS_A]->(:GoTerm)`                  | —                   | GO ontology                                  |
| `(:GoTerm)-[:PART_OF]->(:GoTerm)`               | —                   | GO ontology                                  |

`:REPORTED_IN` leaves a description or an annotation: from a publication, `(b)<-[:REPORTED_IN]-(d:Description)` is what it observed and `(b)<-[:REPORTED_IN]-(a:Annotation)` what it annotated.

### `:INTERACTS_WITH`

The shortcut from one partner of an interaction to the other, so a walk over the interactome is one hop instead of `Protein ← INVOLVES ← Interaction → INVOLVES → Protein`. One edge per `:Interaction`, written from the human protein of a VH and from either of an HH, and always matched **undirected**: `(p)-[:INTERACTS_WITH]-(q)`. Whether it is human–human or virus–human is read from the endpoints' `:Human` and `:Viral` labels.

| property         | type | notes                                               |
| ---------------- | ---- | --------------------------------------------------- |
| `n_descriptions` | int  | copied from the interaction, as are the three below |
| `n_publications` | int  |                                                     |
| `n_methods`      | int  |                                                     |
| `n_peptides`     | int  |                                                     |

`:Interaction` stays the source of truth: the evidence and the peptides are reached through it, and the audit checks that the edge agrees with it. A homodimer is a self-loop, so a query ranking partners still excludes it with `WHERE partner <> self`.

______________________________________________________________________

## 3. Keys

The natural keys, each what `MATCH` targets and a unique constraint holds:

| label          | key                      |
| -------------- | ------------------------ |
| `:Human`       | `accession`              |
| `:Viral`       | `ncbi_taxon_id` + `name` |
| `:Taxon`       | `ncbi_taxon_id`          |
| `:Publication` | `pmid`                   |
| `:GoTerm`      | `go_id`                  |
| `:Peptide`     | `sequence`               |
| `:Curated`     | `stable_id`              |

A node that links others has no key: it is what it links, and the audit checks that it is unique by pattern.

| label          | unique by                                    |
| -------------- | -------------------------------------------- |
| `:Interaction` | its two proteins                             |
| `:IntAct`      | its interaction, its publication, its method |
| `:Annotation`  | its protein, its term, its qualifier         |

A build writes such a node with the edges that make it what it is, in one statement, so nothing ever has to find it again by a key.

______________________________________________________________________

## 4. DDL

Verified against `falkordb/falkordb-server:v4.22.0`, the version `docker-compose.yml` pins. A unique constraint needs a supporting index first, and is applied asynchronously: creating it answers `PENDING`, and `CALL db.constraints()` then reports it `UNDER CONSTRUCTION` until the scan finishes. Both mean *still building* — only `OPERATIONAL` and `FAILED` are verdicts. Applied after the data is loaded; see [`build.md`](build.md).

```cypher
CREATE INDEX FOR (p:Human)       ON (p.accession);
CREATE INDEX FOR (p:Viral)       ON (p.ncbi_taxon_id, p.name);
CREATE INDEX FOR (p:Protein)     ON (p.name);
CREATE INDEX FOR (t:Taxon)       ON (t.ncbi_taxon_id);
CREATE INDEX FOR (t:Taxon)       ON (t.name);
CREATE INDEX FOR (g:GoTerm)      ON (g.go_id);
CREATE INDEX FOR (g:GoTerm)      ON (g.namespace);
CREATE INDEX FOR (b:Publication) ON (b.pmid);
CREATE INDEX FOR (d:Curated)     ON (d.stable_id);
CREATE INDEX FOR (x:Peptide)     ON (x.sequence);
CREATE INDEX FOR (x:Peptide)     ON (x.length);

CALL db.idx.fulltext.createNodeIndex('Publication', 'title', 'abstract');
```

```
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Human       PROPERTIES 1 accession
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Viral       PROPERTIES 2 ncbi_taxon_id name
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Taxon       PROPERTIES 1 ncbi_taxon_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE GoTerm      PROPERTIES 1 go_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Publication PROPERTIES 1 pmid
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Curated     PROPERTIES 1 stable_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Peptide     PROPERTIES 1 sequence
```

______________________________________________________________________

## 5. The sequence vaults

Sequences are not in the graph. A build writes them beside it, one SQLite file per silo in the run's `vault/`, from the same run as the graph. They answer questions about one protein at a time — verifying a hypothesis the graph produced — and are never the basis of reasoning over many. `bpgraph.vault` reads them.

**`host-9606.sqlite`** — `sequence(accession, sequence)`: every Swiss-Prot human entry, keyed by its accession.

**`viral.sqlite`**:

| table         | key                                                   | columns                                                                   |
| ------------- | ----------------------------------------------------- | ------------------------------------------------------------------------- |
| `entry`       | `accession`                                           | `taxon_id`, `taxon_name` (the strain), `description`                      |
| `mature`      | `ncbi_taxon_id`, `name`, `accession`, `start`, `stop` | where a viral protein sits on an entry, 1-based inclusive, and `sequence` |
| `observation` | `stable_id`                                           | `accession`: the viral entry a curated VH description observed            |

A viral protein's sequences are its `mature` rows, keyed as the graph keys the protein, as curation recorded them: as many as places it was observed at. An entry's `description` is UniProt's protein name, empty for an entry UniProt has retired.
