# The graph

## Nodes

- `:Protein`, either `:Human` or `:Viral`: `id` (key), `name` (indexed), `description`, `function`. A human protein's id is its Swiss-Prot accession, a viral protein's `<virus taxon id>:<name>`, e.g. `10407:HBx`. `description` is UniProt's name, `function` its function text.
- `:Taxon:Virus`: `taxon_id` (key), `name` (indexed), `full_name`. `name` is the familiar name (`HBV`), `full_name` the scientific one.
- `:Taxon:Family`: `taxon_id` (key), `name` (indexed).
- `:Publication`: `pmid` (key), `title` and `abstract` (full-text), `journal`, `year`, `authors`. `year` is 0 when PubMed gives none.
- `:Interaction`, either `:HH` or `:VH`: `id` (key), `<side a>|<side b>`, and its evidence: `n_publications` (distinct publications), `n_methods` (distinct PSI-MI methods), `n_descriptions` (observations), `n_peptides` (distinct peptides).
- `:Description`: `id` (key), `intact_id` (indexed), `stable_ids`, `method_id`, `method_name`. One observation: one pair, one publication, one method. `intact_id` is empty unless the observation is IntAct's; `stable_ids` lists our curated rows.
- `:Annotation`: `id` (key), `qualifier`, `evidence_code`, `assigned_by`. An experimental GO annotation of a human protein; a `qualifier` starting `NOT` negates it.
- `:Peptide`: `sequence` (key), `length` (indexed).
- `:GoTerm`: `go_id` (key), `name`, `namespace` (indexed), `obsolete`. `namespace` is `biological_process` or `molecular_function`.

## Relationships

- `(:Interaction)-[:INVOLVES {side}]->(:Protein)`: `side` is `a` or `b`; in `:VH`, `a` is the human protein.
- `(:Protein)-[:INTERACTS_WITH {interaction_id, n_publications, n_methods, n_descriptions, n_peptides}]->(:Protein)`: a shortcut from side `a` to side `b`, one per interaction, with its counters. Match it undirected.
- `(:Description)-[:SUPPORTS]->(:Interaction)`.
- `(:Description)-[:REPORTED_IN]->(:Publication)` and `(:Annotation)-[:REPORTED_IN]->(:Publication)`.
- `(:Description)-[:REPORTS {source_side}]->(:Peptide)`: `source_side` is the side the peptide comes from.
- `(:Protein)-[:FUNCTION_CITES]->(:Publication)`: the publications a protein's function text cites.
- `(:Viral)-[:IN_TAXON]->(:Virus)-[:PARENT]->(:Family)`.
- `(:Annotation)-[:ANNOTATES]->(:Human)` and `(:Annotation)-[:OF_TERM]->(:GoTerm)`.
- `(:GoTerm)-[:IS_A|PART_OF]->(:GoTerm)`: pointing up the ontology.

## Writing Cypher

- Enter through `:Protein`, whose `id` is indexed, and close the filter with `WITH`: `MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human WITH h MATCH (h)-…`. `MATCH (h:Human {id: …})` scans every human protein.
- Close every filtered `MATCH` with `WITH`, carrying every variable its `WHERE` reads: `WITH h, i, v WHERE …`. The engine refuses a `WHERE` on a variable its `WITH` dropped.
- Return the properties and aggregates you need, never whole nodes: `function` and `abstract` are long.
- Partners: `(p)-[e:INTERACTS_WITH]-(q) WHERE q <> p`, matched undirected; `e` carries the counters and `interaction_id`. A homodimer is a self-loop, which `q <> p` drops.
- Sides: through `(p)<-[:INVOLVES]-(i:Interaction)-[:INVOLVES]->(q)`.
- A peptide comes from the partner whose `INVOLVES.side` equals `REPORTS.source_side`, and binds the other.
- GO rollup: `(h)<-[:ANNOTATES]-(a:Annotation)-[:OF_TERM]->(:GoTerm)-[:IS_A|PART_OF*0..]->(g)`, excluding `a.qualifier STARTS WITH 'NOT'`. `regulation of X` is not under `X`.
- Full text: `CALL db.idx.fulltext.queryNodes('Publication', $text) YIELD node, score`.
