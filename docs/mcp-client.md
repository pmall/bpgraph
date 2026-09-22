# bpgraph — schema for query clients

A FalkorDB graph, key **`bpgraph`**, queried in Cypher and read-only. Protein–protein interactions, human–human and virus–human, with the publications, detection methods and peptides behind them; the NCBI taxonomy of the viruses; GO annotations on the human proteins.

## Nodes

Key in bold. Every property is always present; unknown text is `''`.

| label                                 | properties                                                                                          |                                                                                                             |
| ------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `:Protein:Human`                      | **`id`**, `accession`, `start`, `stop`, `name`, `description`, `function`, `taxon_id`, `taxon_name` | `id` = accession (`P36969`), `name` = gene symbol (`GPX4`)                                                  |
| `:Protein:Viral`                      | same                                                                                                | one mature protein of a polyprotein: `id` = `P27958:1973-2419`, `name` = `NS5A`. Several share an accession |
| `:Interaction:HH` / `:Interaction:VH` | **`id`**, `n_descriptions`, `n_publications`, `n_methods`, `n_peptides`                             | the deduplicated claim; the counters are the confidence signal, there is no score                           |
| `:Description`                        | **`id`**                                                                                            | one observation: one pair, one publication, one method                                                      |
| `:Publication`                        | **`pmid`** (string), `title`, `abstract`, `journal`, `year`, `authors` (list)                       |                                                                                                             |
| `:Method`                             | **`psimi_id`** (`MI:0018`), `name`                                                                  | detection method                                                                                            |
| `:Peptide`                            | **`sequence`**, `length`                                                                            | a subsequence reported sufficient for an interaction                                                        |
| `:Taxon`                              | **`taxon_id`**, `name`, `rank`                                                                      | viral species and families only                                                                             |
| `:GoTerm`                             | **`go_id`**, `name`, `namespace`, `obsolete`                                                        | `namespace`: `biological_process`, `molecular_function`, `cellular_component`                               |
| `:ProteinSet`                         | **`name`**                                                                                          | a curated set of human proteins, e.g. `ferroptosis`                                                         |

## Relationships

| pattern                                         | properties                                          |
| ----------------------------------------------- | --------------------------------------------------- |
| `(:Interaction)-[:INVOLVES]->(:Protein)`        | `side`: `'a'` or `'b'`                              |
| `(:Description)-[:SUPPORTS]->(:Interaction)`    |                                                     |
| `(:Description)-[:REPORTED_IN]->(:Publication)` |                                                     |
| `(:Description)-[:DETECTED_BY]->(:Method)`      |                                                     |
| `(:Description)-[:REPORTS]->(:Peptide)`         | `source_side`: `'a'` or `'b'`                       |
| `(:Protein:Viral)-[:IN_TAXON]->(:Taxon)`        | to the species                                      |
| `(:Taxon)-[:PARENT]->(:Taxon)`                  | species → family                                    |
| `(:Protein:Human)-[:MEMBER_OF]->(:ProteinSet)`  | set-specific, e.g. `role`; read them with `keys(r)` |
| `(:Protein:Human)-[:ANNOTATED_WITH]->(:GoTerm)` | `evidence_code`, `assigned_by`, `qualifier`         |
| `(:GoTerm)-[:IS_A\|PART_OF]->(:GoTerm)`         | child → parent                                      |

## Rules

- **Sides.** In a `:VH` interaction side `a` is the human protein and side `b` the viral one. In `:HH` the order means nothing. To list a protein's partners, go `(p)<-[:INVOLVES]-(i)-[:INVOLVES]->(q) WHERE q <> p`; a homodimer is an `:HH` whose two `:INVOLVES` reach the same protein, and that filter drops it.
- **Peptide direction.** The peptide came from the partner whose `INVOLVES.side` equals `REPORTS.source_side`, and binds the other one. Without that comparison, source and target are mixed up.
- **Viral families.** `(:Viral)-[:IN_TAXON]->(:Taxon)-[:PARENT]->(f:Taxon {rank: 'family'})`. A species with no family has no `:PARENT`. Human proteins have no `:Taxon` node.
- **GO.** Only human proteins are annotated, each on the most specific term that fits: roll up with `-[:ANNOTATED_WITH]->(:GoTerm)-[:IS_A|PART_OF*0..]->(t)`. A `qualifier` starting with `NOT|` negates the annotation, so always exclude it. `evidence_code = 'IEA'` is electronic and unreviewed, about a third of them. `regulation of X` is not below `X`: match by name to include it. Term names are not indexed, but `toLower(g.name) CONTAINS 'ferroptosis'` is fast.
- **Publications** have a full-text index on `title` and `abstract`: `CALL db.idx.fulltext.queryNodes('Publication', 'hepatitis') YIELD node`.

## Examples

Which viral families target a protein set:

```cypher
MATCH (:ProteinSet {name: 'ferroptosis'})<-[:MEMBER_OF]-(h:Human)
      <-[:INVOLVES]-(i:VH)-[:INVOLVES]->(:Viral)
      -[:IN_TAXON]->(:Taxon)-[:PARENT]->(f:Taxon {rank: 'family'})
RETURN f.name AS family, count(DISTINCT h) AS targets,
       count(DISTINCT i) AS interactions
ORDER BY targets DESC
```

Human proteins under a GO process, reviewed evidence only, by viral family:

```cypher
MATCH (t:GoTerm {go_id: 'GO:0006915'})
MATCH (h:Human)-[a:ANNOTATED_WITH]->(:GoTerm)-[:IS_A|PART_OF*0..]->(t)
WHERE NOT a.qualifier STARTS WITH 'NOT' AND a.evidence_code <> 'IEA'
MATCH (h)<-[:INVOLVES]-(:VH)-[:INVOLVES]->(:Viral)
      -[:IN_TAXON]->(:Taxon)-[:PARENT]->(f:Taxon {rank: 'family'})
RETURN f.name AS family, count(DISTINCT h) AS targets
ORDER BY targets DESC
```

Peptides and the protein they came from:

```cypher
MATCH (p:Protein)<-[s:INVOLVES]-(i:Interaction)<-[:SUPPORTS]-(:Description)
      -[r:REPORTS]->(x:Peptide)
WHERE s.side = r.source_side
RETURN p.name AS source, x.sequence, i.id
```
