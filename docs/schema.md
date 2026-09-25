# bpgraph — graph schema

FalkorDB is schemaless; **this document is the schema**. Nothing is written to the graph that is not described here. Graph key: `bpgraph`.

Companion documents, load when relevant: [`build.md`](build.md) (how a run builds and validates a graph), [`queries.md`](queries.md) (canonical queries and a worked example).

## Principles

1. **No optional properties.** Every property listed here is always present. Free text that is unknown is `''`, never null or absent.
2. **A single key per label**, and every `MATCH` on a node targets it. Most keys come from the data; only `:Protein` and `:Interaction` derive one (§3).
3. **Labels carry the type, not properties.** Human vs viral, hh vs vh, virus vs family are labels — no `kind` or `rank` property duplicates them.
4. **Reify the n-ary facts.** An interaction observation links two proteins, a publication, a method and some peptides. Cypher edges join exactly two nodes and cannot be an endpoint themselves, so that fact is a node: `:Description`.
5. **Two levels of interaction.** `:Interaction` is the deduplicated claim ("A binds B"); `:Description` is one observation of it, and is one row of the description table.
6. **Sequences only on `:Peptide`.** Peptides are the deliverable; nothing else stores residues.

______________________________________________________________________

## 1. Nodes

### `:Protein` + `:Human` | `:Viral`

What an interaction joins, and what an analysis means by a protein: `GPX4`, `NS5A` of HCV, `HBx` of HBV. Human or viral comes from `labels(p)`.

A **human** protein is a gene product, one UniProt accession. A **viral** protein is a curated mature protein of a curated virus, whichever strains and accessions it was observed on: SARS-CoV-2 `nsp2` is one node, although curation saw it on pp1a, on pp1ab and on a TrEMBL copy, and HBV `HBx` is one node over twenty-one accessions. The accessions are `:Entry` nodes, and `:ON_ENTRY` says where the protein sits on each.

| property      | type | notes                                                                     |
| ------------- | ---- | ------------------------------------------------------------------------- |
| `id`          | str  | **key**, derived (§3)                                                     |
| `name`        | str  | curated mature-protein name (`NS5A`) / gene symbol (`GPX4`). Case matters |
| `description` | str  | UniProt protein name, e.g. `Glutathione peroxidase 4`                     |
| `function`    | str  | UniProt `CC FUNCTION` text, pooled over the protein's entries — see below |

**Names are case-sensitive.** EBV carries `BARF1`, a secreted protein, beside `BaRF1`, the ribonucleotide reductase small subunit. Folding case would merge them.

**`function` is pooled.** UniProt text is per entry, and per chain where the entry scopes it; a viral protein on several entries has several. Curation groups one chain across strains, so they should agree, and the protein takes the commonest, weighted by how many descriptions observed each entry. The build logs every protein whose entries disagree.

### `:Entry`

A UniProt accession, canonical — never an isoform. The strain lives here rather than on a node of its own.

| property      | type | notes                                                               |
| ------------- | ---- | ------------------------------------------------------------------- |
| `accession`   | str  | **key**                                                             |
| `taxon_id`    | int  | NCBI taxon of the entry, a strain as often as not. `9606` for human |
| `taxon_name`  | str  | its NCBI scientific name                                            |
| `description` | str  | UniProt protein name of the entry, e.g. `Genome polyprotein`        |

An entry carries human proteins or viral ones, never both. A human protein is on exactly one entry, its own accession.

### `:Taxon` + `:Virus` | `:Family`

Only the curated viruses a viral protein belongs to, and the family above each. Human proteins get no `:Taxon` node, and strains get none either: they are `taxon_id` on `:Entry`.

`:Virus` — one row of [`curation/viruses.tsv`](../curation/viruses.tsv), which [`curation/viruses.md`](../curation/viruses.md) explains. A viral protein belongs to the most specific row enclosing its entry's taxon.

| property    | type | notes                                              |
| ----------- | ---- | -------------------------------------------------- |
| `taxon_id`  | int  | **key**, the NCBI taxon the virus is anchored at   |
| `name`      | str  | familiar short name: `HBV`, `SARS-CoV-2`, `HPV16`  |
| `full_name` | str  | scientific name of that taxon: `Hepatitis B virus` |

`:Family` — the NCBI family above a virus.

| property   | type | notes           |
| ---------- | ---- | --------------- |
| `taxon_id` | int  | **key**         |
| `name`     | str  | scientific name |

The virus level is curated rather than an NCBI rank: NCBI attaches entries to strains, and its species sometimes pool viruses nobody would, *Betacoronavirus pandemicum* holding both SARS-CoV-2 and SARS-CoV. The `:PARENT` edge from a virus to its family is derived at build time from the NCBI taxonomy, which this repo keeps in SQLite (`bpgraph.taxonomy`). A virus with no family gets no edge: it stays queryable, it just falls out of family rollups.

### `:Topic`

A subject of study (`ferroptosis`), curated as a list of human proteins — not a GO term. The lists are not in the export; see [`export.md`](export.md).

| property | type | notes   |
| -------- | ---- | ------- |
| `name`   | str  | **key** |

### `:Publication`

| property   | type  | notes   |
| ---------- | ----- | ------- |
| `pmid`     | str   | **key** |
| `title`    | str   |         |
| `abstract` | str   |         |
| `journal`  | str   |         |
| `year`     | int   |         |
| `authors`  | [str] |         |

### `:Method`

| property   | type | notes                   |
| ---------- | ---- | ----------------------- |
| `psimi_id` | str  | **key**, e.g. `MI:0018` |
| `name`     | str  | e.g. `two hybrid`       |

### `:Interaction` + `:HH` | `:VH`

The deduplicated claim that two proteins interact. Because a viral protein pools its strains, so does the claim: every description of HBx binding a human protein supports one interaction, whichever HBV accession it was observed on. No provenance of its own — that hangs off `:Description`. The counters are the confidence signal; there is no score. `:HH` and `:VH` appear on no other label, so `MATCH (i:VH)` is unambiguous.

| property         | type | notes                                                         |
| ---------------- | ---- | ------------------------------------------------------------- |
| `id`             | str  | **key**, derived (§3)                                         |
| `n_descriptions` | int  | supporting descriptions                                       |
| `n_publications` | int  | **distinct** publications                                     |
| `n_methods`      | int  | **distinct** detection methods                                |
| `n_peptides`     | int  | distinct peptides; `> 0` answers "do we have a peptide here?" |

Slot ordering is fixed, carries no biological direction, and exists only to make the id deterministic:

- **`:VH`** — side `a` is the **human** protein, side `b` the viral one.
- **`:HH`** — side `a` is whichever of the two ids sorts first alphabetically, side `b` the other. Human ids are bare accessions (§3), so this is accession order.

Human-first generalizes: add a `:BH` later and queries entering from the human side still need not know the type.

**A homodimer is an ordinary `:HH`** whose two `:INVOLVES` edges point at the same protein — `id` is the accession joined to itself, and both slots are filled as usual. Entering from a protein therefore reaches it twice, once per side, so a query that ranks a protein's partners excludes it with `WHERE partner <> self` unless self-binding is what it is asking about.

### `:Description`

One row of the description table: one protein pair, one publication, one method, its peptides, and the entry each partner was observed on. Everything about it is its edges. Its type is its interaction's — `(d)-[:SUPPORTS]->(:VH)`.

| property | type | notes                                                  |
| -------- | ---- | ------------------------------------------------------ |
| `id`     | str  | **key** — the `stable_id` from the relational database |

### `:Peptide`

A short subsequence reported sufficient for an interaction — the drug-discovery precursor, and the only place residues are stored. One node per unique sequence: where in its source protein it sits is not stored, so the same sequence seen in two viruses collapses onto one node. Source and target are proteins, not entries.

| property   | type | notes   |
| ---------- | ---- | ------- |
| `sequence` | str  | **key** |
| `length`   | int  |         |

A peptide is directed — derived *from* one partner, binding the other — but that is a fact about one description, not about the peptide, so it lives on the `:REPORTS` edge (§2). A homodimer's peptides all come from side `a`: source and target are one node, and the distinction does not arise.

### `:GoTerm`

| property    | type | notes                                                              |
| ----------- | ---- | ------------------------------------------------------------------ |
| `go_id`     | str  | **key**, e.g. `GO:0097707`                                         |
| `name`      | str  |                                                                    |
| `namespace` | str  | `biological_process` / `molecular_function` / `cellular_component` |
| `obsolete`  | bool |                                                                    |

Annotated terms **plus their full ancestor closure**, so rolling up to a coarse process is a traversal, not a lookup table. Only the three namespace roots have no parent; every other term sits under one. All three namespaces are loaded and a query cuts to the one it wants on `namespace` — `biological_process` is the process axis, `molecular_function` the mechanistic one, `cellular_component` the compartment one.

GO is the structured functional layer; `description` and `function` on `:Protein` say the same thing in prose. UniProt's smaller controlled vocabularies — keywords, InterPro/Pfam — would each follow this pattern if a query ever wants them; subcellular location arrives as `cellular_component` already. None are modelled until then.

**Only human proteins are annotated.** GOA annotates a whole accession, while a viral protein here is one mature chain of a polyprotein, and nothing in GOA says which chain a term belongs to — see [`export.md`](export.md).

______________________________________________________________________

## 2. Relationships

| pattern                                         | properties                                  | meaning                                     |
| ----------------------------------------------- | ------------------------------------------- | ------------------------------------------- |
| `(:Interaction)-[:INVOLVES]->(:Protein)`        | `side: 'a'\|'b'`                            | the two partners                            |
| `(:Protein)-[:ON_ENTRY]->(:Entry)`              | viral: `start`, `stop`; human: none         | an accession the protein was observed on    |
| `(:Description)-[:SUPPORTS]->(:Interaction)`    | —                                           | observation → claim                         |
| `(:Description)-[:OBSERVED_ON]->(:Entry)`       | `side: 'a'\|'b'`                            | the accession each side was observed on     |
| `(:Description)-[:REPORTED_IN]->(:Publication)` | —                                           |                                             |
| `(:Description)-[:DETECTED_BY]->(:Method)`      | —                                           |                                             |
| `(:Description)-[:REPORTS]->(:Peptide)`         | `source_side: 'a'\|'b'`                     | the peptide, and which partner it came from |
| `(:Viral)-[:IN_TAXON]->(:Virus)`                | —                                           | the curated virus                           |
| `(:Virus)-[:PARENT]->(:Family)`                 | —                                           | virus → family                              |
| `(:Human)-[:INVOLVED_IN]->(:Topic)`             | per topic, see below                        | from the curated list                       |
| `(:Human)-[:ANNOTATED_WITH]->(:GoTerm)`         | `evidence_code`, `assigned_by`, `qualifier` | from UniProt/GOA                            |
| `(:GoTerm)-[:IS_A]->(:GoTerm)`                  | —                                           | GO ontology                                 |
| `(:GoTerm)-[:PART_OF]->(:GoTerm)`               | —                                           | GO ontology                                 |

### `:ON_ENTRY` properties

The properties depend on the protein's label, as `:INVOLVED_IN`'s depend on the topic. A **viral** edge carries `start` and `stop`, 1-based inclusive on the entry's sequence: where the mature protein was excised. A viral protein has one edge per entry and span it was observed at, so pp1a and pp1ab each carry an edge to one `nsp2`. A **human** edge carries nothing: a human protein is the whole chain of its one entry.

### `:OBSERVED_ON`

Pooling proteins across strains loses which accession an observation used, from the interaction. The description keeps it: one `:OBSERVED_ON` per side, tagged like `:INVOLVES`, so `(d)-[:OBSERVED_ON {side: 'b'}]->(e)` is the entry the viral partner was seen on. That entry is always one the side's protein is `:ON_ENTRY`. A homodimer has two edges to the one entry.

### Peptide direction

`:REPORTS` carries `source_side`, naming the side of *this description's* interaction the peptide came from. The description points at one interaction, whose partners are tagged `side: 'a'` and `side: 'b'`, so one property pins down both source and target — however many of each the peptide accumulates across the graph.

Entering from a protein, compare that protein's own `INVOLVES.side` against `source_side`: equal means the protein is the peptide's **source**, different means it is the **target**. Omitting the comparison silently mixes the two. Worked queries are in [`queries.md`](queries.md).

### `:INVOLVED_IN` properties

Each topic records its own things about its proteins, so the properties depend on the topic — they are its list's columns, verbatim, as text. A topic is added here with its properties, or the audit rejects it.

| topic         | properties | values                                                                                                          |
| ------------- | ---------- | --------------------------------------------------------------------------------------------------------------- |
| `ferroptosis` | `role`     | `driver` promotes ferroptosis, `suppressor` holds it back, `both` does either depending on context. From FerrDB |

### Derived shortcuts (optional)

`(:Protein)-[:INTERACTS_WITH]->(:Protein)` with `n_publications`, `n_methods`, shortening 2-hop traversals to 1. Stored in the canonical direction only and always matched **undirected**. `:Interaction` stays the source of truth; build this only if traversals become a nuisance.

______________________________________________________________________

## 3. Keys

Every label has one key property, and it is what `MERGE` and `MATCH` target. Most come straight from the data:

| label          | key         |                                       |
| -------------- | ----------- | ------------------------------------- |
| `:Entry`       | `accession` | from the data                         |
| `:Peptide`     | `sequence`  |                                       |
| `:Publication` | `pmid`      |                                       |
| `:Method`      | `psimi_id`  |                                       |
| `:GoTerm`      | `go_id`     |                                       |
| `:Taxon`       | `taxon_id`  |                                       |
| `:Topic`       | `name`      |                                       |
| `:Description` | `id`        | the relational database's `stable_id` |
| `:Protein`     | `id`        | **derived** — see below               |
| `:Interaction` | `id`        | **derived**                           |

Only two are derived, because only two are identified by several values at once and composite keys are painful to reference from another node. Both live in `src/bpgraph/ids.py`, the only place these rules are encoded:

```
human_protein_id(accession)       -> accession                   "P36969"
viral_protein_id(taxon_id, name)  -> f"{taxon_id}:{name}"        "10407:HBx"
    taxon_id is the curated virus's, not the entry's

interaction_id(id_a, id_b)        -> f"{id_a}|{id_b}"            "P36969|10407:HBx"
    a, b in the slot order of §1
```

Coordinates and accessions are not part of a viral id: they are annotations on `:ON_ENTRY`.

______________________________________________________________________

## 4. DDL

Verified against `falkordb/falkordb-server:latest` (graph module 4.20.6). A unique constraint needs a supporting index first, and is applied asynchronously: creating it answers `PENDING`, and `CALL db.constraints()` then reports it `UNDER CONSTRUCTION` until the scan finishes. Both mean *still building* — only `OPERATIONAL` and `FAILED` are verdicts. Applied after the data is loaded; see [`build.md`](build.md).

```cypher
CREATE INDEX FOR (p:Protein)     ON (p.id);
CREATE INDEX FOR (p:Protein)     ON (p.name);
CREATE INDEX FOR (e:Entry)       ON (e.accession);
CREATE INDEX FOR (e:Entry)       ON (e.taxon_id);
CREATE INDEX FOR (t:Taxon)       ON (t.taxon_id);
CREATE INDEX FOR (t:Taxon)       ON (t.name);
CREATE INDEX FOR (t:Topic)       ON (t.name);
CREATE INDEX FOR (g:GoTerm)      ON (g.go_id);
CREATE INDEX FOR (g:GoTerm)      ON (g.namespace);
CREATE INDEX FOR (b:Publication) ON (b.pmid);
CREATE INDEX FOR (m:Method)      ON (m.psimi_id);
CREATE INDEX FOR (i:Interaction) ON (i.id);
CREATE INDEX FOR (d:Description) ON (d.id);
CREATE INDEX FOR (x:Peptide)     ON (x.sequence);
CREATE INDEX FOR (x:Peptide)     ON (x.length);

CALL db.idx.fulltext.createNodeIndex('Publication', 'title', 'abstract');
```

```
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Protein     PROPERTIES 1 id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Entry       PROPERTIES 1 accession
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Taxon       PROPERTIES 1 taxon_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Topic       PROPERTIES 1 name
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE GoTerm      PROPERTIES 1 go_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Publication PROPERTIES 1 pmid
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Method      PROPERTIES 1 psimi_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Interaction PROPERTIES 1 id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Description PROPERTIES 1 id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Peptide     PROPERTIES 1 sequence
```
