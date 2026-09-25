# bpgraph — querying

How to explore the graph: answering questions, and the analysis skills. See [`schema.md`](schema.md) for the model.

## Reaching the graph

Query the live graph `bpgraph` on the FalkorDB server, and nothing else. It is the only source of truth. **Do not read `data/`** to answer a question: it holds the raw sources of a build, some of which never reach the graph, and they would contradict it. If the graph lacks something, say so rather than looking elsewhere.

Explore through the `bpgraph` MCP server, at `http://localhost:8080/mcp` and registered in `.mcp.json`. Its `query` tool runs one read-only Cypher statement, with values passed as `$name` placeholders in `params`, and returns one object per row. The database refuses writes.

A node comes back as its properties plus `_labels`, an edge as its properties plus `_type`. Return the properties you need rather than whole nodes: a protein's `function` and a publication's `abstract` are long. The text is where the value is, though. Read it once you have narrowed down to the proteins and publications that matter.

The same query runs from a terminal, one JSON object per row, and scripts call `bpgraph.query.rows`:

```sh
uv run bpgraph-query "MATCH (t:Topic) RETURN t.name"
uv run bpgraph-query --params '{"topic": "ferroptosis"}' < query.cypher
```

## Rules

- **Sides.** In a `:VH` interaction side `a` is the human protein and side `b` the viral one. In `:HH` the order means nothing. To list a protein's partners, go `(p)<-[:INVOLVES]-(i)-[:INVOLVES]->(q) WHERE q <> p`. A homodimer is an `:HH` whose two `:INVOLVES` reach the same protein, and that filter drops it.
- **Peptide direction.** The peptide came from the partner whose `INVOLVES.side` equals `REPORTS.source_side`, and binds the other one. Without that comparison, source and target are mixed up.
- **Viral proteins** are curated: `NS5A` of HCV is one `:Protein`, pooled over every strain and accession it was observed on, so its interactions and counters are pooled too. Name one by virus and name: `(p:Viral {name: 'HBx'})-[:IN_TAXON]->(:Virus {name: 'HBV'})`, or by id, `10407:HBx`. Names are case-sensitive.
- **Viruses and families.** `(:Viral)-[:IN_TAXON]->(v:Virus)-[:PARENT]->(f:Family)`. `v.name` is the familiar name (`HBV`, `SARS-CoV-2`), `v.full_name` the scientific one. A virus with no family has no `:PARENT`. Human proteins have no `:Taxon` node.
- **Accessions and strains** are `:Entry` nodes. `(p)-[:ON_ENTRY]->(e:Entry)` lists what a protein was observed on, with `start`/`stop` on the edge for viral proteins; `e.taxon_name` is the strain. `(d:Description)-[:OBSERVED_ON {side}]->(e)` is the entry one observation used. Go through entries only when a question is about strains or sequences.
- **GO.** Only human proteins are annotated, each on the most specific term that fits: roll up with `-[:ANNOTATED_WITH]->(:GoTerm)-[:IS_A|PART_OF*0..]->(t)`. A `qualifier` starting with `NOT|` negates the annotation, so always exclude it. `evidence_code = 'IEA'` is electronic and unreviewed, about a third of them. `regulation of X` is not below `X`: match by name to include it. Term names are not indexed, but `toLower(g.name) CONTAINS 'ferroptosis'` is fast.
- **Publications** have a full-text index on `title` and `abstract`: `CALL db.idx.fulltext.queryNodes('Publication', 'hepatitis') YIELD node`.
- **Evidence.** The counters on `:Interaction` are the confidence signal; there is no score.

______________________________________________________________________

## Worked example

*HCV NS5A (observed on P27958, 1973–2419) binds human GPX4 (P36969), reported in PMID 12345678 by two-hybrid and by anti-bait coIP, with the peptide `PSLKATC` from NS5A sufficient for the interaction.*

This is exactly the graph [`docs/example-export/`](example-export) builds, so every value below can be loaded and queried rather than taken on trust. `function` is empty because it is fetched per run rather than exported — see [`export.md`](export.md).

```
(:Protein:Human {id:"P36969", name:"GPX4",
                 description:"Phospholipid hydroperoxide glutathione peroxidase",
                 function:""})
    -[:ON_ENTRY]-> (:Entry {accession:"P36969", taxon_id:9606,
                            taxon_name:"Homo sapiens", description:"Phospholipid…"})
(:Protein:Viral {id:"3052230:NS5A", name:"NS5A",
                 description:"Genome polyprotein", function:""})
    -[:ON_ENTRY {start:1973, stop:2419}]-> (:Entry {accession:"P27958",
                            taxon_id:3052230, taxon_name:"Orthohepacivirus hominis",
                            description:"Genome polyprotein"})
    -[:IN_TAXON]-> (:Taxon:Virus {taxon_id:3052230, name:"HCV",
                                  full_name:"Orthohepacivirus hominis"})
    -[:PARENT]->   (:Taxon:Family {taxon_id:3700683, name:"Hepaciviridae"})

(:Interaction:VH {id:"P36969|3052230:NS5A",
                  n_descriptions:2, n_publications:1, n_methods:2, n_peptides:1})
    -[:INVOLVES {side:"a"}]-> (P36969)              <- human is always side a
    -[:INVOLVES {side:"b"}]-> (3052230:NS5A)

(:Description {id:"D-00417"})                       <- stable_id from the source
    -[:SUPPORTS]->     (:Interaction:VH {id:"P36969|3052230:NS5A"})
    -[:OBSERVED_ON {side:"a"}]-> (:Entry {accession:"P36969"})
    -[:OBSERVED_ON {side:"b"}]-> (:Entry {accession:"P27958"})
    -[:REPORTED_IN]->  (:Publication {pmid:"12345678", …})
    -[:DETECTED_BY]->  (:Method {psimi_id:"MI:0018", name:"two hybrid"})
    -[:REPORTS {source_side:"b"}]-> (:Peptide {sequence:"PSLKATC", length:7})
```

`source_side: "b"` is what makes the peptide directed: side `b` is NS5A, so the peptide is *from* NS5A and *binds* GPX4. `D-00418` is the same pair by a second method, so it adds one `:Description`, bumps `n_descriptions` and `n_methods`, and reuses everything else. Had it observed NS5A on another HCV accession, it would still support the same interaction, and only its `:OBSERVED_ON` would differ.

The same export also reports `PSLKATC` from GPX4 against ACSL4 (`D-00901`), and that reuses the one `:Peptide` node — on an `:HH` interaction whose side `a` is `O60488`, because two human ids order alphabetically. The pairing stays exact even so, because each description names its own source side.

The taxon shows something else: the export says `11103`, the graph says `3052230`. NCBI retired the former, and the loader follows the merge before placing the entry under its curated virus.

______________________________________________________________________

## Differential: how do viral families act on a topic?

```cypher
MATCH (h:Human)-[m:INVOLVED_IN]->(:Topic {name: $topic})
MATCH (h)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(v:Viral)
MATCH (v)-[:IN_TAXON]->(:Virus)-[:PARENT]->(f:Family)
RETURN f.name AS family, m.role AS role,
       count(DISTINCT h) AS n_targets,
       count(DISTINCT i) AS n_interactions,
       collect(DISTINCT h.name)[0..15] AS targets
ORDER BY n_targets DESC
```

## Peptides available against a topic — the shortlist

```cypher
MATCH (h:Human)-[:INVOLVED_IN]->(:Topic {name: $topic})
MATCH (i:VH)-[:INVOLVES {side: 'a'}]->(h)
MATCH (i)-[:INVOLVES {side: 'b'}]->(v:Viral)
MATCH (i)<-[:SUPPORTS]-(:Description)-[:REPORTS {source_side: 'b'}]->(x:Peptide)
MATCH (v)-[:IN_TAXON]->(virus:Virus)-[:PARENT]->(f:Family)
RETURN x.sequence, x.length, virus.name + ' ' + v.name AS source, f.name AS family,
       collect(DISTINCT h.name) AS targets
ORDER BY x.length ASC
```

## Peptides *targeting* one protein, with their evidence

The `hv.side <> r.source_side` test is what excludes peptides *derived from* this protein. Flip it to `=` for the other direction — without it the two are silently mixed.

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

Never enter from the peptide. A peptide node is shared across every target it was reported against, so this collects evidence for all of them:

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
MATCH (h:Human)-[:INVOLVED_IN]->(:Topic {name: $topic})
MATCH (h)<-[:INVOLVES]-(i:VH)-[:INVOLVES]->(v:Viral)
WHERE i.n_peptides = 0 AND i.n_publications >= 2
MATCH (v)-[:IN_TAXON]->(virus:Virus)
RETURN virus.name AS virus, v.name AS viral, h.name AS human,
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
MATCH (v:Viral)-[:IN_TAXON]->(:Virus)-[:PARENT]->(:Family {name: $family})
MATCH (v)<-[:INVOLVES]-(:VH)-[:INVOLVES]->(h:Human)
MATCH (h)-[r:ANNOTATED_WITH]->(:GoTerm)-[:IS_A|PART_OF*0..]->
      (g:GoTerm {namespace: 'biological_process'})
WHERE NOT r.qualifier STARTS WITH 'NOT'
RETURN g.name, count(DISTINCT h) AS n_proteins
ORDER BY n_proteins DESC LIMIT 40
```

`*0..` is what makes this a rollup: zero hops keeps the terms the proteins are annotated with, and every hop above them is an ancestor the build loaded for exactly this. **Filter the qualifier.** GOA states what a protein is *not* involved in as an ordinary annotation with `NOT` in front of its qualifier, so counting it would put the protein in the one process it is known to stay out of.

Swap `namespace` to ask the same question along another axis: `molecular_function` for the activities a family engages, `cellular_component` for the compartments it reaches.

## Human interactome context around a topic

First-shell partners the topic does not itself involve, ranked by support. The `n <> h` test does double duty: it drops the topic's own proteins, and it drops the homodimers, whose two `:INVOLVES` edges both land on `h` itself.

```cypher
MATCH (h:Human)-[:INVOLVED_IN]->(:Topic {name: $topic})
MATCH (h)<-[:INVOLVES]-(i:HH)-[:INVOLVES]->(n:Human)
WHERE n <> h AND NOT (n)-[:INVOLVED_IN]->(:Topic {name: $topic})
RETURN n.name, max(i.n_publications) AS best_support,
       count(DISTINCT h) AS n_topic_neighbours
ORDER BY n_topic_neighbours DESC, best_support DESC
```

## Which strains and accessions back a claim

A viral protein pools its strains. To see which entries an interaction's observations actually used:

```cypher
MATCH (i:Interaction {id: $interaction_id})<-[:SUPPORTS]-(d:Description)
MATCH (d)-[:OBSERVED_ON {side: 'b'}]->(e:Entry)
MATCH (d)-[:REPORTED_IN]->(b:Publication)
RETURN e.accession, e.taxon_name AS strain,
       count(DISTINCT d) AS descriptions, collect(DISTINCT b.pmid) AS pmids
ORDER BY descriptions DESC
```
