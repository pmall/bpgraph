# bpgraph — canonical queries

The queries this schema is optimized for. Keep them working. See
[`schema.md`](schema.md) for the model.

## Worked example

*HCV NS5A (P27958, 1973–2419) binds human GPX4 (P36969), reported in PMID
12345678 by two-hybrid and by anti-bait coIP, with the peptide `PSLKATC` from
NS5A sufficient for the interaction.*

This is exactly the graph [`docs/example-export/`](example-export) builds, so
every value below can be loaded and queried rather than taken on trust.
`function` is empty because it is fetched per export into `data/` rather than
exported — see [`export.md`](export.md).

```
(:Protein:Human {id:"P36969", accession:"P36969", start:1, stop:197,
                 name:"GPX4",
                 description:"Phospholipid hydroperoxide glutathione peroxidase",
                 function:"",
                 taxon_id:9606, taxon_name:"Homo sapiens"})
(:Protein:Viral {id:"P27958:1973-2419", accession:"P27958",
                 start:1973, stop:2419, name:"NS5A",
                 description:"Genome polyprotein",
                 function:"", taxon_id:3052230,
                 taxon_name:"Orthohepacivirus hominis"})

(:Interaction:VH {id:"P36969|P27958:1973-2419",
                  n_descriptions:2, n_publications:1, n_methods:2, n_peptides:1})
    -[:INVOLVES {side:"a"}]-> (P36969)              <- human is always side a
    -[:INVOLVES {side:"b"}]-> (P27958:1973-2419)

(:Description {id:"D-00417"})                       <- stable_id from the source
    -[:SUPPORTS]->     (:Interaction:VH {id:"P36969|…"})
    -[:REPORTED_IN]->  (:Publication {pmid:"12345678", …})
    -[:DETECTED_BY]->  (:Method {psimi_id:"MI:0018", name:"two hybrid"})
    -[:REPORTS {source_side:"b"}]-> (:Peptide {sequence:"PSLKATC", length:7})

(P27958:1973-2419) -[:IN_TAXON]-> (:Taxon {taxon_id:3052230, rank:"species",
                                           name:"Orthohepacivirus hominis"})
                      -[:PARENT]-> (:Taxon {taxon_id:3700683, rank:"family",
                                            name:"Hepaciviridae"})
(P36969) -[:MEMBER_OF {role:"inhibitor", mechanism:"GPX4 axis"}]->
         (:ProteinSet {name:"ferroptosis"})
```

`source_side: "b"` is what makes the peptide directed: side `b` is NS5A, so the
peptide is *from* NS5A and *binds* GPX4. `D-00418` is the same pair by a second
method, so it adds one `:Description`, bumps `n_descriptions` and `n_methods`,
and reuses everything else.

The same export also reports `PSLKATC` from GPX4 against ACSL4 (`D-00901`), and
that reuses the one `:Peptide` node — on an `:HH` interaction whose side `a` is
`O60488`, because two human ids order alphabetically. The pairing stays exact
even so, because each description names its own source side.

The taxon shows something else: the export says `11103`, the graph says
`3052230`. NCBI retired the former, and the loader follows the merge, so the
graph only ever holds ids and names NCBI still uses.

---

## Differential: how do viral families act on a protein set?

```cypher
MATCH (h:Human)-[m:MEMBER_OF]->(:ProteinSet {name: $set})
MATCH (h)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(v:Viral)
MATCH (v)-[:IN_TAXON]->(:Taxon)-[:PARENT*1..]->(f:Taxon {rank: 'family'})
RETURN f.name AS family, m.role AS role,
       count(DISTINCT h) AS n_targets,
       count(DISTINCT i) AS n_interactions,
       collect(DISTINCT h.name)[0..15] AS targets
ORDER BY n_targets DESC
```

## Peptides available against a protein set — the shortlist

```cypher
MATCH (h:Human)-[:MEMBER_OF]->(:ProteinSet {name: $set})
MATCH (i:VH)-[:INVOLVES {side: 'a'}]->(h)
MATCH (i)-[:INVOLVES {side: 'b'}]->(v:Viral)
MATCH (i)<-[:SUPPORTS]-(:Description)-[:REPORTS {source_side: 'b'}]->(x:Peptide)
MATCH (v)-[:IN_TAXON]->(:Taxon)-[:PARENT*1..]->(f:Taxon {rank: 'family'})
RETURN x.sequence, x.length, v.name AS source, f.name AS family,
       collect(DISTINCT h.name) AS targets
ORDER BY x.length ASC
```

## Peptides *targeting* one protein, with their evidence

The `hv.side <> r.source_side` test is what excludes peptides *derived from*
this protein. Flip it to `=` for the other direction — without it the two are
silently mixed.

```cypher
MATCH (h:Protein {id: $pid})<-[hv:INVOLVES]-(i:Interaction)<-[:SUPPORTS]-(d:Description)
MATCH (d)-[r:REPORTS]->(x:Peptide)  WHERE hv.side <> r.source_side
MATCH (i)-[sv:INVOLVES]->(s:Protein) WHERE sv.side =  r.source_side
MATCH (d)-[:REPORTED_IN]->(b:Publication)
MATCH (d)-[:DETECTED_BY]->(m:Method)
RETURN x.sequence, x.length, s.name AS source,
       collect(DISTINCT b.pmid) AS pmids, collect(DISTINCT m.name) AS methods
ORDER BY size(pmids) DESC
```

Never enter from the peptide. A peptide node is shared across every target it
was reported against, so this collects evidence for all of them:

```cypher
// WRONG
MATCH (x:Peptide {sequence: $seq})<-[:REPORTS]-(:Description)-[:REPORTED_IN]->(b:Publication)
RETURN collect(b.pmid) AS evidence
```

## What does this peptide do? — the peptide as a hub

```cypher
MATCH (x:Peptide {sequence: $seq})<-[r:REPORTS]-(d:Description)-[:SUPPORTS]->(i:Interaction)
MATCH (i)-[sv:INVOLVES]->(s:Protein) WHERE sv.side =  r.source_side
MATCH (i)-[tv:INVOLVES]->(t:Protein) WHERE tv.side <> r.source_side
MATCH (d)-[:REPORTED_IN]->(b:Publication)
RETURN s.name AS source, t.name AS target, b.pmid, b.year
ORDER BY b.year DESC
```

## Well-supported interactions lacking a peptide — where to look next

```cypher
MATCH (h:Human)-[:MEMBER_OF]->(:ProteinSet {name: $set})
MATCH (h)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(v:Viral)
WHERE i.n_peptides = 0 AND i.n_publications >= 2
RETURN v.name AS viral, h.name AS human,
       i.n_publications, i.n_methods, i.n_descriptions
ORDER BY i.n_publications DESC, i.n_methods DESC
```

## Evidence behind a claim

```cypher
MATCH (i:Interaction {id: $interaction_id})<-[:SUPPORTS]-(d:Description)
MATCH (d)-[:REPORTED_IN]->(b:Publication)
MATCH (d)-[:DETECTED_BY]->(m:Method)
RETURN b.pmid, b.year, b.title, m.name,
       [(d)-[:REPORTS]->(x:Peptide) | x.sequence] AS peptides
ORDER BY b.year DESC
```

## Everything one publication described

```cypher
MATCH (b:Publication {pmid: $pmid})<-[:REPORTED_IN]-(d:Description)
                                   -[:SUPPORTS]->(i:Interaction)
                                   -[:INVOLVES]->(p:Protein)
RETURN i.id, collect(p.name) AS partners
```

## Process-level rollup — which processes does a viral family reach?

```cypher
MATCH (v:Viral)-[:IN_TAXON]->(:Taxon)-[:PARENT*1..]->(:Taxon {name: $family})
MATCH (v)<-[:INVOLVES]-(:VH)-[:INVOLVES]->(h:Human)
MATCH (h)-[r:ANNOTATED_WITH]->(:GoTerm)-[:IS_A|PART_OF*0..]->
      (g:GoTerm {namespace: 'biological_process'})
WHERE NOT r.qualifier STARTS WITH 'NOT'
RETURN g.name, count(DISTINCT h) AS n_proteins
ORDER BY n_proteins DESC LIMIT 40
```

`*0..` is what makes this a rollup: zero hops keeps the terms the proteins are
annotated with, and every hop above them is an ancestor the build loaded for
exactly this. **Filter the qualifier.** GOA states what a protein is *not*
involved in as an ordinary annotation with `NOT` in front of its qualifier, so
counting it would put the protein in the one process it is known to stay out
of.

Swap `namespace` to ask the same question along another axis:
`molecular_function` for the activities a family engages, `cellular_component`
for the compartments it reaches.

## Human interactome context around a set

First-shell partners that are not themselves members, ranked by support. The
`n <> h` test does double duty: it drops the members, and it drops the
homodimers, whose two `:INVOLVES` edges both land on `h` itself.

```cypher
MATCH (h:Human)-[:MEMBER_OF]->(:ProteinSet {name: $set})
MATCH (h)<-[:INVOLVES]-(i:HH)-[:INVOLVES]->(n:Human)
WHERE n <> h AND NOT (n)-[:MEMBER_OF]->(:ProteinSet {name: $set})
RETURN n.name, max(i.n_publications) AS best_support,
       count(DISTINCT h) AS n_member_neighbours
ORDER BY n_member_neighbours DESC, best_support DESC
```
