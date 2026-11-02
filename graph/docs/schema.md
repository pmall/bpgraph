# bpgraph — graph schema

FalkorDB is schemaless; **this document is the schema**. Nothing is written to the graph that is not described here. Graph key: `bpgraph`.

Companion documents, load when relevant: [`build.md`](build.md) (how a run builds and validates a graph), [`roadmap.md`](roadmap.md) (where the schema is going).

## Principles <a id="principles"></a>

- **A graph, not tables.** An entity is keyed by its natural key, the value the world names it by. A natural key that is a single value, such as a publication's `pmid`, is the property itself. A key that joins several values is a composite key, and every value it joins is a property: a viral protein is `NS5A` of virus `3052230`, a name meaningless without its taxon, so it is keyed by `ncbi_taxon_id` and `name`, never by an id `<taxon_id>:<name>`. A node that links entities — an interaction, a description, an annotation — has no key of its own: it is what it links, and its own properties where they change what it states, and its uniqueness is checked by pattern, as [the keys](#keys) say. The keys of the nodes it points to are not repeated on it, and a detail about a fact, such as how it was shown or who recorded it, is not part of its key. No id is ever derived by joining values into a string: a value present only inside an id is a missing property, and a caller names a node by its key's values.
- **No optional properties.** Every property listed here is always present. Free text that is unknown is `''`, never null or absent.
- **Labels carry the type, not properties.** Human vs viral, HH vs VH, virus vs family, curated vs IntAct are labels — no `kind` or `source` property duplicates them.
- **Reify the n-ary facts.** An interaction observation links a pair, a publication and some peptides; a GO annotation links a protein, a term and publications. Cypher edges join exactly two nodes and cannot be an endpoint themselves, so those facts are nodes: `:Description` and `:Annotation`. What only qualifies one link is a property of that edge.
- **Two levels of interaction.** `:Interaction` is the deduplicated claim ("A binds B"); `:Description` is one observation of it, in one publication, by one method.
- **Every fact we did not curate points at a publication.** Interactions, GO annotations and function text come in only when a publication backs them, and the publication is a node an agent can read.
- **Sequences only on `:Peptide`.** Peptides are the deliverable; every other sequence is in the [sequence vaults](#vaults) beside the graph, never in it.

______________________________________________________________________

## Nodes

### `:Protein` + `:Human` | `:Viral` <a id="protein"></a>

What an interaction joins, and what an analysis means by a protein: `GPX4`, `NS5A` of HCV, `HBx` of HBV. Human or viral comes from `labels(p)`.

A **human** protein is one reviewed UniProt entry, keyed by its accession. **Every** Swiss-Prot human entry is a protein of the graph, whether or not an interaction names it, each with its function text and GO annotations.

| property      | type | notes                                                 |
| ------------- | ---- | ----------------------------------------------------- |
| `accession`   | str  | **key**, the Swiss-Prot accession                     |
| `name`        | str  | gene symbol, `GPX4`                                   |
| `description` | str  | UniProt protein name, e.g. `Glutathione peroxidase 4` |
| `function`    | str  | UniProt `CC FUNCTION` text                            |

A **viral** protein is a curated mature protein of a virus, whichever strains and accessions it was observed on, as curation groups them: SARS-CoV-2 `nsp2` is one node, although curation saw it on pp1a, on pp1ab and on a TrEMBL copy, and HBV `HBx` is one node over every accession curation saw it on. A name means nothing without its virus, so a viral protein is keyed by both. Which accessions, at which spans, and in which strains, is kept in the viral [sequence vault](#vaults), not in the graph.

| property        | type | notes                                                   |
| --------------- | ---- | ------------------------------------------------------- |
| `ncbi_taxon_id` | int  | **key**, with `name`: its virus's NCBI taxon id         |
| `name`          | str  | **key**, with `ncbi_taxon_id`: the curated protein name |
| `function`      | str  | UniProt `CC FUNCTION` text, every distinct one          |

**Names are case-sensitive.** EBV carries `BARF1`, a secreted protein, beside `BaRF1`, the ribonucleotide reductase small subunit. Folding case would merge them.

**A viral protein keeps every function text its members carry.** Only reviewed entries give function text: an unreviewed entry's is automatic annotation citing no publication. UniProt text is per entry, and per chain where the entry scopes it; a viral protein on several entries has several. Curation groups one chain across strains, and the texts are worded by different curators, so none is picked: `function` holds each distinct text once, as paragraphs separated by a blank line. The publications UniProt cites for the texts are `:FUNCTION_CITES` edges. A viral protein has no UniProt `description`: the name UniProt gives an entry is the entry's, a polyprotein's for most mature proteins, not the protein's.

### `:Taxon` + `:Virus` | `:Family`

Only the viruses viral proteins belong to, and the family above each. Human proteins get no `:Taxon` node, and strains get none either: they are in the viral vault.

`:Virus` — the species taxon curation groups a viral protein under, as the export names it.

| property        | type | notes                                                          |
| --------------- | ---- | -------------------------------------------------------------- |
| `ncbi_taxon_id` | int  | **key**, the species taxon id, as curation gives it            |
| `name`          | str  | its scientific name, as curation gives it: `Hepatitis B virus` |

`:Family` — the NCBI family above a virus.

| property        | type | notes           |
| --------------- | ---- | --------------- |
| `ncbi_taxon_id` | int  | **key**         |
| `name`          | str  | scientific name |

The virus level is curation's: NCBI attaches UniProt entries to strains, and curation decides which species taxon each protein belongs to, taking its strains with it. The build does no grouping of its own. The `:PARENT` edge from a virus to its family is derived at build time from the NCBI taxonomy, following NCBI's merges from the id curation gives, which this repo keeps in SQLite (`bpgraph.taxonomy`). A virus with no family gets no edge: it stays queryable, it just falls out of family rollups.

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

### `:Description` + `:Curated` | `:IntAct` <a id="description"></a>

One observation of an interaction: one pair, one publication, one method, and its peptides. Its method is two properties; everything else about it is its edges. Its type is its interaction's — `(d)-[:SUPPORTS]->(:VH)`.

A **`:Curated`** description is one row of our curation, keyed by its `stable_id`: one row, one description, however many rows link the same pair, publication and method — a paper testing several strains of a virus is one row per strain. Every VH description is curated.

An **`:IntAct`** description is IntAct's, of a publication we have not curated for HH interactions: we read such a publication and decided what it shows, so all IntAct could add is what we decided against. A publication we curated for VH rows only does not count, IntAct's records being human–human. IntAct records sharing a pair, a publication and a method are one description, which has no key.

| property      | type | notes                                                   |
| ------------- | ---- | ------------------------------------------------------- |
| `stable_id`   | str  | `:Curated` only, **key**: our curation's id for the row |
| `method_id`   | str  | PSI-MI id of the detection method, e.g. `MI:0018`       |
| `method_name` | str  | PSI-MI's name, e.g. `two hybrid`                        |

The method is a property because it joins nothing: a description has exactly one, and no query walks from a method to its descriptions. Two methods are two descriptions.

### `:Annotation` <a id="annotation"></a>

What GO states about a human protein: that it has a function or takes part in a process — the term — as its qualifier says, shown by publications. One per protein, term and qualifier; it is a node because it joins a protein, a term and publications, and has no key: it is what it links.

| property    | type | notes                                                                                                                              |
| ----------- | ---- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `qualifier` | str  | how the protein relates to the term: `enables`, `involved_in`, `contributes_to`, `acts_upstream_of…`; `NOT\|…` states the opposite |

How each publication shows it is on its `:REPORTED_IN` edge: `evidence_codes`, the experimental codes GOA gives that publication for it. Which database recorded it is not kept. Electronic and inferred annotations are not loaded: they cite no publication.

**`NOT` is a finding, not an absence.** `NOT|involved_in` says a paper showed the protein does not take part in the process; such an annotation must never be read as the protein having the function.

**Function only.** Two parts of GO are not loaded. `cellular_component`, the whole namespace, because where a protein sits is not what it does, and much of it is proteomics listing everything a purified fraction held. And `protein binding` (`GO:0005515`) with every term below it — `identical protein binding`, `enzyme binding`, `ubiquitin protein ligase binding`… — because such an annotation says the protein binds another protein: an interaction, which `:Interaction` states better, naming the partner.

### `:Peptide`

A short subsequence reported sufficient for an interaction, of 5 to 20 residues — the drug-discovery precursor, and the only place residues are stored. Curation maps longer regions too; only the peptides among them are loaded. One node per sequence, which is its key: the same sequence seen in two proteins is one peptide.

| property   | type | notes   |
| ---------- | ---- | ------- |
| `sequence` | str  | **key** |
| `length`   | int  |         |

It is described by its edges: `:FROM` each protein it was cut from — the protein, whichever isoform it was mapped on — `:BINDS` each protein it was shown to bind, and the curated descriptions that `:REPORTS` it. A homodimer's peptide binds its own source. Within one description, the peptide comes from the one of its two proteins it is `:FROM`, and binds the other; the build fails a description reporting a peptide from both.

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

## Relationships

| pattern                                         | properties                           | meaning                                 |
| ----------------------------------------------- | ------------------------------------ | --------------------------------------- |
| `(:Interaction)-[:INVOLVES]->(:Protein)`        | —                                    | the two partners                        |
| `(:Description)-[:SUPPORTS]->(:Interaction)`    | —                                    | observation → claim                     |
| `(:Description)-[:REPORTED_IN]->(:Publication)` | —                                    |                                         |
| `(:Curated)-[:REPORTS]->(:Peptide)`             | —                                    | a peptide the observation reported      |
| `(:Peptide)-[:FROM]->(:Protein)`                | —                                    | a protein the peptide was cut from      |
| `(:Peptide)-[:BINDS]->(:Protein)`               | —                                    | a protein the peptide was shown to bind |
| `(:Annotation)-[:ANNOTATES]->(:Human)`          | —                                    | the annotated protein                   |
| `(:Annotation)-[:OF_TERM]->(:GoTerm)`           | —                                    | the term, the most specific that fits   |
| `(:Annotation)-[:REPORTED_IN]->(:Publication)`  | `evidence_codes`                     | a publication showing it, and how       |
| `(:Protein)-[:FUNCTION_CITES]->(:Publication)`  | —                                    | evidence UniProt cites for `function`   |
| `(:Viral)-[:IN_TAXON]->(:Virus)`                | —                                    | the virus, of the protein's taxon id    |
| `(:Virus)-[:PARENT]->(:Family)`                 | —                                    | virus → family                          |
| `(:Protein)-[:INTERACTS_WITH]->(:Protein)`      | [the four counters](#interacts-with) | shortcut over an interaction            |
| `(:GoTerm)-[:IS_A]->(:GoTerm)`                  | —                                    | GO ontology                             |
| `(:GoTerm)-[:PART_OF]->(:GoTerm)`               | —                                    | GO ontology                             |

`:REPORTED_IN` leaves a description or an annotation: from a publication, `(b)<-[:REPORTED_IN]-(d:Description)` is what it observed and `(b)<-[:REPORTED_IN]-(a:Annotation)` what it annotated.

### `:INTERACTS_WITH` <a id="interacts-with"></a>

The shortcut from one partner of an interaction to the other, so a walk over the interactome is one hop instead of `Protein ← INVOLVES ← Interaction → INVOLVES → Protein`. One edge per `:Interaction`, written from the human protein of a VH and from either of an HH, and always matched **undirected**: `(p)-[:INTERACTS_WITH]-(q)`. Whether it is human–human or virus–human is read from the endpoints' `:Human` and `:Viral` labels.

| property         | type | notes                       |
| ---------------- | ---- | --------------------------- |
| `n_descriptions` | int  | copied from the interaction |
| `n_publications` | int  | copied from the interaction |
| `n_methods`      | int  | copied from the interaction |
| `n_peptides`     | int  | copied from the interaction |

`:Interaction` stays the source of truth: the evidence and the peptides are reached through it, and the audit checks that the edge agrees with it. A homodimer is a self-loop, so a query ranking partners still excludes it with `WHERE partner <> self`.

______________________________________________________________________

## Keys <a id="keys"></a>

The natural keys, each what `MATCH` targets and a unique constraint holds, which a build must pass before it is published; `bpgraph.schema` creates them, with the indexes queries need:

| label          | key                      |
| -------------- | ------------------------ |
| `:Human`       | `accession`              |
| `:Viral`       | `ncbi_taxon_id` + `name` |
| `:Taxon`       | `ncbi_taxon_id`          |
| `:Publication` | `pmid`                   |
| `:GoTerm`      | `go_id`                  |
| `:Peptide`     | `sequence`               |
| `:Curated`     | `stable_id`              |

A node that links others has no key: it is what it links, and is unique by pattern, as [invariants](#invariants) `I1`, `D4` and `A3` say.

| label          | unique by                                    |
| -------------- | -------------------------------------------- |
| `:Interaction` | its two proteins                             |
| `:IntAct`      | its interaction, its publication, its method |
| `:Annotation`  | its protein, its term, its qualifier         |

______________________________________________________________________

## Invariants <a id="invariants"></a>

What the graph holds beyond its keys, each rule with an ID that never changes. `bpgraph-audit` checks every one on the live graph, and names a rule it finds broken by its ID.

| ID  | invariant                                                                                                                                           |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1  | Every node carries a label this document defines.                                                                                                   |
| S2  | A node carries exactly the properties its label lists, of the types listed.                                                                         |
| S3  | A `:Protein`, an `:Interaction`, a `:Taxon` and a `:Description` carries exactly one of its two type labels.                                        |
| S4  | An edge joins the labels its relationship gives, and carries exactly the properties it lists.                                                       |
| I1  | One interaction per pair of proteins.                                                                                                               |
| I2  | An interaction has two `:INVOLVES` edges.                                                                                                           |
| I3  | A `:VH` joins a human protein and a viral one, an `:HH` two human proteins.                                                                         |
| I4  | An interaction's counters equal what they count: its descriptions, their distinct publications, their distinct methods and their distinct peptides. |
| I5  | One `:INTERACTS_WITH` per interaction, between its two proteins, copying its counters.                                                              |
| I6  | Every interaction has a description.                                                                                                                |
| D1  | A description supports one interaction, and is reported in one publication.                                                                         |
| D2  | A `:Curated` description's `stable_id` is not empty.                                                                                                |
| D3  | A description's `method_id` is a PSI-MI id, `MI:0018`, and its `method_name` is not empty.                                                          |
| D4  | One `:IntAct` description per interaction, publication and method.                                                                                  |
| D5  | No `:IntAct` description is of a publication we curated for HH interactions.                                                                        |
| D6  | Every VH description is `:Curated`.                                                                                                                 |
| D7  | An `:IntAct` description's method is one `curation/methods.tsv` keeps.                                                                              |
| D8  | No interaction has `:IntAct` descriptions from two publications of one group of `curation/publications.tsv`.                                        |
| A1  | An annotation annotates one protein, with one term.                                                                                                 |
| A2  | Every annotation is reported in a publication.                                                                                                      |
| A3  | One annotation per protein, term and qualifier.                                                                                                     |
| A4  | Each publication of an annotation shows it by experimental evidence codes, one at least.                                                            |
| A5  | No annotation is to a `cellular_component` term, nor to `protein binding` or a term below it.                                                       |
| G1  | Every term is a `biological_process` or a `molecular_function`.                                                                                     |
| G2  | Every term but the two namespace roots has a parent.                                                                                                |
| G3  | Every term is annotated, or lies above a term that is.                                                                                              |
| T1  | A viral protein has one `:IN_TAXON`, to the virus of its `ncbi_taxon_id`.                                                                           |
| T2  | A human protein has no `:IN_TAXON`.                                                                                                                 |
| T3  | A virus has one family at most.                                                                                                                     |
| T4  | Every virus has a viral protein, and every family a virus.                                                                                          |
| P1  | A peptide's `length` is its residue count, 5 to 20, and its residues are upper case.                                                                |
| P2  | Every peptide is reported by a curated description, comes from a protein and binds one.                                                             |
| P3  | Of the two proteins of a description reporting a peptide, exactly one is its source, and it binds one at least.                                     |
| B1  | Every publication backs a description, an annotation or a function text.                                                                            |

______________________________________________________________________

## The sequence vaults <a id="vaults"></a>

Sequences are not in the graph. A build writes them beside it, one SQLite file per silo, from the same run as the graph. They answer questions about one protein at a time — verifying a hypothesis the graph produced — and are never the basis of reasoning over many, for the reasons [`roadmap.md`](roadmap.md#principles) gives. The host vault holds the sequence of every Swiss-Prot human entry. The viral vault holds every place a viral protein was observed, keyed as the graph keys the protein: each entry and span as curation recorded them, of the UniProt release curation gives, with the entry's strain; and the entry each curated VH description observed. `bpgraph.vault` gives their tables.
