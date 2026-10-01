## Writing Cypher

- Enter through `:Protein`, whose `id` is indexed, and close the filter with `WITH`: `MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human WITH h MATCH (h)-…`. `MATCH (h:Human {id: …})` scans every human protein.
- Close every filtered `MATCH` with `WITH`, carrying every variable its `WHERE` reads: `WITH h, i, v WHERE …`. The engine refuses a `WHERE` on a variable its `WITH` dropped.
- Pass values as `params`, `$name` in the statement.
- Return the properties and aggregates you need, never whole nodes: `function` and `abstract` are long.
- Partners: `(p)-[e:INTERACTS_WITH]-(q) WHERE q <> p`, matched undirected; `e` carries the counters and `interaction_id`. A homodimer is a self-loop, which `q <> p` drops.
- Sides: through `(p)<-[:INVOLVES]-(i:Interaction)-[:INVOLVES]->(q)`. In `:VH`, side `a` is the human protein.
- A peptide comes from the partner whose `INVOLVES.side` equals `REPORTS.source_side`, and binds the other.
- GO rollup: `(h)<-[:ANNOTATES]-(a:Annotation)-[:OF_TERM]->(:GoTerm)-[:IS_A|PART_OF*0..]->(g)`, excluding `a.qualifier STARTS WITH 'NOT'`. `regulation of X` is not under `X`.
- Full text: `CALL db.idx.fulltext.queryNodes('Publication', $text) YIELD node, score`.
- A hub (ubiquitin, chaperones, the baits of large screens) links almost everything: a path through one says little.

## Examples

Golden VH interactions of a set with no peptide yet:

```cypher
MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
WITH h
MATCH (h)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(v:Viral)
WITH h, i, v
WHERE i.n_peptides = 0 AND (i.n_publications >= 2 OR i.n_methods >= 2)
MATCH (v)-[:IN_TAXON]->(t:Virus)
RETURN t.name AS virus, v.name AS viral, h.name AS human,
       i.n_publications AS n_publications, i.n_methods AS n_methods
ORDER BY n_publications DESC, n_methods DESC
```

Families reaching each protein of a set through golden interactions:

```cypher
MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
WITH h
MATCH (h)-[e:INTERACTS_WITH]-(v:Viral)
WITH h, e, v
WHERE e.n_publications >= 2 OR e.n_methods >= 2
MATCH (v)-[:IN_TAXON]->(:Virus)-[:PARENT]->(f:Family)
RETURN h.name AS protein, count(DISTINCT f) AS n_families,
       collect(DISTINCT f.name) AS families
ORDER BY n_families DESC, protein
```

Each protein's golden partners within a set, beside its partners across the proteome:

```cypher
MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
WITH h
MATCH (h)-[e:INTERACTS_WITH]-(n:Human)
WITH h, e, n
WHERE n <> h AND (e.n_publications >= 2 OR e.n_methods >= 2)
RETURN h.name AS protein,
       count(DISTINCT CASE WHEN n.id IN $accessions THEN n END) AS in_set,
       count(DISTINCT n) AS in_proteome
ORDER BY in_set DESC, in_proteome DESC
```

Human proteins two proteins both bind:

```cypher
MATCH (a:Protein {id: $a})-[:INTERACTS_WITH]-(m:Human)
WITH a, m WHERE m <> a
MATCH (m)-[:INTERACTS_WITH]-(b:Protein {id: $b})
WITH m, b WHERE m <> b
RETURN m.id AS id, m.name AS name
ORDER BY name
```
