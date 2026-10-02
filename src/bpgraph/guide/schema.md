# The graph

## Nodes

- `:Protein:Human`: `accession` (key), `name` (indexed, the gene symbol), `description` (UniProt's name), `function` (UniProt's function text).
- `:Protein:Viral`: `ncbi_taxon_id` and `name` (together the key: `NS5A` of virus `3052230`), `function`. A viral protein pools every strain of its virus it was observed on.
- `:Taxon:Virus`: `ncbi_taxon_id` (key), `name` (indexed), `full_name`. `name` is the familiar name (`HBV`), `full_name` the scientific one.
- `:Taxon:Family`: `ncbi_taxon_id` (key), `name` (indexed).
- `:Publication`: `pmid` (key), `title` and `abstract` (full-text), `journal`, `year`, `authors`. `year` is 0 when PubMed gives none.
- `:Interaction`, either `:HH` or `:VH`: no key, it is its two proteins. Its evidence: `n_publications` (distinct publications), `n_methods` (distinct PSI-MI methods), `n_descriptions` (observations), `n_peptides` (distinct peptides).
- `:Description`, either `:Curated` or `:IntAct`: one observation, one pair, one publication, one method: `method_id`, `method_name`. A `:Curated` one is a row of our curation, `stable_id` (key); an `:IntAct` one is IntAct's, of a publication we did not curate. Every VH description is curated.
- `:Annotation`: `qualifier`. What GO states about a human protein and a term, one per protein, term and qualifier; a `qualifier` starting `NOT` states the opposite.
- `:Peptide`: `sequence` (key), `length` (indexed).
- `:GoTerm`: `go_id` (key), `name`, `namespace` (indexed): `biological_process` or `molecular_function`.

## Relationships

- `(:Interaction)-[:INVOLVES]->(:Protein)`: its two proteins; a homodimer's both point at one.
- `(:Protein)-[:INTERACTS_WITH {n_publications, n_methods, n_descriptions, n_peptides}]->(:Protein)`: a shortcut between an interaction's two proteins, with its counters. Match it undirected.
- `(:Description)-[:SUPPORTS]->(:Interaction)` and `(:Description)-[:REPORTED_IN]->(:Publication)`.
- `(:Curated)-[:REPORTS]->(:Peptide)`, `(:Peptide)-[:FROM]->(:Protein)` the proteins it was cut from, `(:Peptide)-[:BINDS]->(:Protein)` the ones it binds.
- `(:Annotation)-[:ANNOTATES]->(:Human)`, `(:Annotation)-[:OF_TERM]->(:GoTerm)`, `(:Annotation)-[:REPORTED_IN {evidence_codes}]->(:Publication)`: each publication showing it, and how.
- `(:Protein)-[:FUNCTION_CITES]->(:Publication)`: the publications a protein's function text cites.
- `(:Viral)-[:IN_TAXON]->(:Virus)-[:PARENT]->(:Family)`.
- `(:GoTerm)-[:IS_A|PART_OF]->(:GoTerm)`: pointing up the ontology.

## Writing Cypher

- Enter through a key, and close the filter with `WITH`: `MATCH (h:Human) WHERE h.accession IN $accessions WITH h MATCH (h)-…`, `MATCH (v:Viral {ncbi_taxon_id: $taxon, name: $name})`.
- Close every filtered `MATCH` with `WITH`, carrying every variable its `WHERE` reads: `WITH h, i, v WHERE …`. The engine refuses a `WHERE` on a variable its `WITH` dropped.
- Return the properties and aggregates you need, never whole nodes: `function` and `abstract` are long.
- Partners: `(p)-[e:INTERACTS_WITH]-(q) WHERE q <> p`, matched undirected; `e` carries the counters. A homodimer is a self-loop, which `q <> p` drops.
- A pattern may use one edge twice: `(p)<-[r:INVOLVES]-(i)-[s:INVOLVES]->(q)` needs `r <> s` to reach both proteins of `i`.
- Under a GO term: `(h)<-[:ANNOTATES]-(a:Annotation)-[:OF_TERM]->(:GoTerm)-[:IS_A|PART_OF*0..]->(g)`, excluding `a.qualifier STARTS WITH 'NOT'`. `regulation of X` is not under `X`.
- Full text: `CALL db.idx.fulltext.queryNodes('Publication', $text) YIELD node, score`.

## Patterns

A question is one pattern, not a chain of queries. For example:

- A virus's interactions down to what reports them: `(t:Virus)<-[:IN_TAXON]-(v:Viral)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(h:Human)`, then `(i)<-[:SUPPORTS]-(d:Description)-[:REPORTED_IN]->(b:Publication)`.
- Through a protein in between: `(v:Viral)-[:INTERACTS_WITH]-(m:Human)-[:INTERACTS_WITH]-(h:Human)`.
- Peptides binding a protein, and where they come from: `(s:Protein)<-[:FROM]-(x:Peptide)-[:BINDS]->(h:Human)`.
- What a publication backs: `(b:Publication)<-[:REPORTED_IN]-(d:Description)-[:SUPPORTS]->(i)`, `(b)<-[:REPORTED_IN]-(:Annotation)`, `(b)<-[:FUNCTION_CITES]-(:Protein)`.
