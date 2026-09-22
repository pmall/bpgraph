# bpgraph — graph schema

FalkorDB is schemaless; **this document is the schema**. Nothing is written to the graph that is not described here. Graph key: `bpgraph`.

Companion documents, load when relevant: [`build.md`](build.md) (how a run builds and validates a graph), [`queries.md`](queries.md) (canonical queries and a worked example).

## Principles

1. **No optional properties.** Every property listed here is always present. Free text that is unknown is `''`, never null or absent.
2. **A single key per label**, and `MERGE`/`MATCH` always targets it. Most keys come from the data; only `:Protein` and `:Interaction` derive one (§4).
3. **Labels carry the type, not properties.** Human vs viral, hh vs vh are labels — no `kind` property duplicates them.
4. **Reify the n-ary facts.** An interaction observation links two proteins, a publication, a method and some peptides. Cypher edges join exactly two nodes and cannot be an endpoint themselves, so that fact is a node: `:Description`.
5. **Two levels of interaction.** `:Interaction` is the deduplicated claim ("A binds B"); `:Description` is one observation of it, and is one row of the description table.
6. **Sequences only on `:Peptide`.** Peptides are the deliverable; nothing else stores residues.

______________________________________________________________________

## 1. Nodes

### `:Protein` + `:Human` | `:Viral`

A protein entity: a full-length human chain, or a mature viral protein excised from a polyprotein. Human or viral comes from `labels(p)`.

| property      | type | notes                                                               |
| ------------- | ---- | ------------------------------------------------------------------- |
| `id`          | str  | **key**, derived (§4)                                               |
| `accession`   | str  | UniProt accession, canonical — never an isoform                     |
| `start`       | int  | 1-based inclusive, on the accession's sequence                      |
| `stop`        | int  | 1-based inclusive                                                   |
| `name`        | str  | standardized mature-protein name (`NS5A`) / gene symbol (`GPX4`)    |
| `description` | str  | UniProt protein name, e.g. `Glutathione peroxidase 4`               |
| `function`    | str  | UniProt `CC FUNCTION` text — the chain's, where the entry scopes it |
| `taxon_id`    | int  | NCBI taxon id                                                       |
| `taxon_name`  | str  | NCBI scientific name                                                |

Coordinates are stored for every protein — `1..length` for human, where they are redundant. That is deliberate: a composite constraint only applies to nodes carrying **all** its properties, so omitting them would leave `(accession, start, stop)` inert for half the graph.

### `:Taxon`

Only viral species and their families, only where a protein links to them. Human proteins get no `:Taxon` node — they carry `taxon_id: 9606` and `taxon_name` as properties, and nothing groups them by clade.

| property   | type | notes                                                       |
| ---------- | ---- | ----------------------------------------------------------- |
| `taxon_id` | int  | **key**                                                     |
| `name`     | str  | scientific name                                             |
| `rank`     | str  | NCBI's rank, verbatim: `species`, `family`, often `no rank` |

The `:PARENT` chain is **derived** at build time from the NCBI taxonomy, which this repo keeps in SQLite (`bpgraph.taxonomy`). Each taxon links to the nearest kept ancestor — only a protein's own taxon and the family above it are kept, so a taxon links straight past whatever ranks lie between. A taxon with no family gets no edge: it stays queryable, it just falls out of family rollups. Adding a rank to keep is a one-line change, and the chain rebuilds itself.

`rank` is NCBI's own, so it is an open vocabulary rather than a fixed pair. Two of the three viruses checked against the real dump — HIV-1 and HSV-1 — sit at `no rank`, so constraining it would have rejected them.

### `:ProteinSet`

A curated per-project set of proteins of interest (`ferroptosis`) — not a GO pathway.

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

The deduplicated claim that two proteins interact. No provenance of its own — that hangs off `:Description`. The counters are the confidence signal; there is no score. `:HH` and `:VH` appear on no other label, so `MATCH (i:VH)` is unambiguous.

| property         | type | notes                                                         |
| ---------------- | ---- | ------------------------------------------------------------- |
| `id`             | str  | **key**, derived (§4)                                         |
| `n_descriptions` | int  | supporting descriptions                                       |
| `n_publications` | int  | **distinct** publications                                     |
| `n_methods`      | int  | **distinct** detection methods                                |
| `n_peptides`     | int  | distinct peptides; `> 0` answers "do we have a peptide here?" |

Slot ordering is fixed, carries no biological direction, and exists only to make the id deterministic:

- **`:VH`** — side `a` is the **human** protein, side `b` the viral one.
- **`:HH`** — side `a` is whichever of the two ids sorts first alphabetically, side `b` the other. Human ids are bare accessions (§4), so this is accession order.

Human-first generalizes: add a `:BH` later and queries entering from the human side still need not know the type.

**A homodimer is an ordinary `:HH`** whose two `:INVOLVES` edges point at the same protein — `id` is the accession joined to itself, and both slots are filled as usual. Entering from a protein therefore reaches it twice, once per side, so a query that ranks a protein's partners excludes it with `WHERE partner <> self` unless self-binding is what it is asking about.

### `:Description`

One row of the description table: one protein pair, one publication, one method, its peptides. Everything about it is its edges. Its type is its interaction's — `(d)-[:SUPPORTS]->(:VH)`.

| property | type | notes                                                  |
| -------- | ---- | ------------------------------------------------------ |
| `id`     | str  | **key** — the `stable_id` from the relational database |

### `:Peptide`

A short subsequence reported sufficient for an interaction — the drug-discovery precursor, and the only place residues are stored. One node per unique sequence: where in its source protein it sits is not stored, so the same sequence seen in two viruses collapses onto one node.

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
| `(:Description)-[:SUPPORTS]->(:Interaction)`    | —                                           | observation → claim                         |
| `(:Description)-[:REPORTED_IN]->(:Publication)` | —                                           |                                             |
| `(:Description)-[:DETECTED_BY]->(:Method)`      | —                                           |                                             |
| `(:Description)-[:REPORTS]->(:Peptide)`         | `source_side: 'a'\|'b'`                     | the peptide, and which partner it came from |
| `(:Protein)-[:IN_TAXON]->(:Taxon)`              | —                                           | viral only, to the `species` node           |
| `(:Taxon)-[:PARENT]->(:Taxon)`                  | —                                           | species → family                            |
| `(:Protein)-[:MEMBER_OF]->(:ProteinSet)`        | arbitrary, see below                        | curated membership                          |
| `(:Protein)-[:ANNOTATED_WITH]->(:GoTerm)`       | `evidence_code`, `assigned_by`, `qualifier` | human only, from UniProt/GOA                |
| `(:GoTerm)-[:IS_A]->(:GoTerm)`                  | —                                           | GO ontology                                 |
| `(:GoTerm)-[:PART_OF]->(:GoTerm)`               | —                                           | GO ontology                                 |

### Peptide direction

`:REPORTS` carries `source_side`, naming the side of *this description's* interaction the peptide came from. The description points at one interaction, whose partners are tagged `side: 'a'` and `side: 'b'`, so one property pins down both source and target — however many of each the peptide accumulates across the graph.

Entering from a protein, compare that protein's own `INVOLVES.side` against `source_side`: equal means the protein is the peptide's **source**, different means it is the **target**. Omitting the comparison silently mixes the two. Worked queries are in [`queries.md`](queries.md).

### `:MEMBER_OF` metadata

Arbitrary key/value pairs written in one shot with `SET r += $attrs`, e.g. `{role: 'inhibitor', mechanism: 'GPX4 axis'}`. The engine restricts values to **scalars or arrays of scalars**; a nested map is rejected. Allowed keys per set are validated in Python, not in the graph.

### Derived shortcuts (optional)

`(:Protein)-[:INTERACTS_WITH]->(:Protein)` with `n_publications`, `n_methods`, shortening 2-hop traversals to 1. Stored in the canonical direction only and always matched **undirected**. `:Interaction` stays the source of truth; build this only if traversals become a nuisance.

______________________________________________________________________

## 3. Keys

Every label has one key property, and it is what `MERGE` and `MATCH` target. Most come straight from the data:

| label          | key        |                                       |
| -------------- | ---------- | ------------------------------------- |
| `:Peptide`     | `sequence` | from the data                         |
| `:Publication` | `pmid`     |                                       |
| `:Method`      | `psimi_id` |                                       |
| `:GoTerm`      | `go_id`    |                                       |
| `:Taxon`       | `taxon_id` |                                       |
| `:ProteinSet`  | `name`     |                                       |
| `:Description` | `id`       | the relational database's `stable_id` |
| `:Protein`     | `id`       | **derived** — see below               |
| `:Interaction` | `id`       | **derived**                           |

Only two are derived, because only two are identified by several values at once and composite keys are painful to reference from another node. Both live in `src/bpgraph/ids.py`, the only place these rules are encoded:

```
protein_id(accession, start, stop, kind)
    -> accession                       when human
    -> f"{accession}:{start}-{stop}"   when viral
    e.g.  "Q53FA7"  /  "P27958:1973-2419"

interaction_id(id_a, id_b)
    -> f"{id_a}|{id_b}"                a, b in the slot order of §1
    e.g.  "Q53FA7|P27958:1973-2419"
```

A human id is a bare accession, so a UniProt release revising a sequence updates `stop` in place and leaves every interaction referencing it untouched. It also encodes the invariant *one node per human accession*, which the `id` constraint enforces.

______________________________________________________________________

## 4. DDL

Verified against `falkordb/falkordb-server:latest` (graph module 4.20.6). A unique constraint needs a supporting index first, and is applied asynchronously: creating it answers `PENDING`, and `CALL db.constraints()` then reports it `UNDER CONSTRUCTION` until the scan finishes. Both mean *still building* — only `OPERATIONAL` and `FAILED` are verdicts. Applied after the data is loaded; see [`build.md`](build.md).

```cypher
CREATE INDEX FOR (p:Protein)     ON (p.id);
CREATE INDEX FOR (p:Protein)     ON (p.accession, p.start, p.stop);
CREATE INDEX FOR (p:Protein)     ON (p.name);
CREATE INDEX FOR (p:Protein)     ON (p.taxon_id);
CREATE INDEX FOR (t:Taxon)       ON (t.taxon_id);
CREATE INDEX FOR (t:Taxon)       ON (t.rank);
CREATE INDEX FOR (s:ProteinSet)  ON (s.name);
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
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Protein     PROPERTIES 3 accession start stop
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Taxon       PROPERTIES 1 taxon_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE ProteinSet  PROPERTIES 1 name
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE GoTerm      PROPERTIES 1 go_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Publication PROPERTIES 1 pmid
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Method      PROPERTIES 1 psimi_id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Interaction PROPERTIES 1 id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Description PROPERTIES 1 id
GRAPH.CONSTRAINT CREATE bpgraph_staging UNIQUE NODE Peptide     PROPERTIES 1 sequence
```
