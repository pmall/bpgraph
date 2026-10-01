# bpgraph — exploring the graph

How to explore bpgraph, a knowledge graph of protein–protein interactions, human–human (HH) and virus–human (VH). Every interaction is backed by the publications that report it, titles and abstracts included. Every human protein of Swiss-Prot is there, with its UniProt function text and its experimental GO annotations of what it does, each tied to the publication showing it. A viral protein is a curated one, such as `HBx` of HBV, under its virus and that virus's family.

The graph produces hypotheses: its counters say where the evidence is, and its text says what the evidence means. Read abstracts and function text once a question is narrowed down; that is where the insight is.

## Reaching the graph

Reach it through the tools of the `bpgraph` MCP server, and nothing else. The graph is the only source of truth: if it lacks something, say so rather than filling the gap from memory, and mark anything taken from the web as such.

Start with the predefined tools. Each answers a question analyses keep asking, and handles the pitfalls below for you; its description says what it returns and what to call next. Write Cypher with the `cypher` tool only for what none of them answers, after reading the `schema` tool.

| question                                                                                | tools                                                                |
| --------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| What does the graph hold? Which viruses, families, viral proteins?                      | `overview`, `viruses`, `viral_proteins`                              |
| Which protein is this name? What does it do?                                            | `find_proteins`, `proteins`                                          |
| Who does a protein bind?                                                                | `partners`                                                           |
| Which viral proteins bind a set of human proteins, a family or a virus?                 | `vh_interactions`                                                    |
| How do human proteins of a set bind each other, or their surroundings?                  | `hh_interactions`, `neighbours`                                      |
| Which viruses reach a set through one human protein in between?                         | `indirect_reach`                                                     |
| How much of a set does each family or virus reach, against its overall reach?           | `coverage`                                                           |
| What observations back an interaction?                                                  | `evidence`                                                           |
| Which peptides bind a protein, or come from it? What does one peptide do?               | `peptides`, `peptide`                                                |
| What does a paper say, and what does it back in the graph? Which papers mention a word? | `publications`, `publication_content`, `search_publications`         |
| What do proteins do, and what do they share? Which proteins does a GO term gather?      | `go_annotations`, `go_rollup`, `search_go_terms`, `go_term_proteins` |
| What is a protein's sequence?                                                           | `human_sequences`, `viral_sequences`                                 |

### How the tools answer

- **A list comes back as `rows` and `total`**, how many rows the question has whatever `limit` kept. When `total` is larger than the rows, raise `limit` or narrow the question; count from `total`, never from a cut list.
- **Size is your call.** A result larger than `max_tokens`, 25,000 by default and estimated at three characters of JSON per token, is refused with its size, its row count and its total, never cut. Narrow the question, lower `limit`, or raise `max_tokens` when your context can take it. `cypher` runs your statement as written, under the same rule.
- **An unknown name is an error** naming the closest known ones, whether a family, virus, protein, GO term, pmid, interaction or peptide. A gene symbol given where an id is expected is answered with its id.
- **Evidence levels.** Tools that filter interactions take `min_publications`, `min_methods` and `combine`. The **golden dataset** is an interaction backed by at least 2 distinct publications or at least 2 distinct detection methods: `min_publications: 2, min_methods: 2, combine: "or"`. An `or` with a threshold of 1 keeps every interaction, and is refused.

## What the data means

- **Viral proteins are curated.** `NS5A` of HCV is one protein, pooled over every strain and accession it was observed on, so its interactions and counters are pooled too. Its id is `<virus taxon id>:<name>`, e.g. `10407:HBx`; names are case-sensitive, and EBV has both `BARF1` and `BaRF1`. `viral_sequences` gives each strain's residues.
- **Evidence is per interaction**: one viral protein with one human protein, or two human proteins. Apply a threshold to each on its own; never add counters across viral proteins or viruses to push a pair over it. Counting how many families reach a protein, each through golden interactions, is fine; summing their publications is not.
- **The counters are the evidence**, and there is no score: `n_publications` distinct publications, `n_methods` distinct PSI-MI detection methods, `n_descriptions` observations, `n_peptides` distinct peptides. Every distinct PSI-MI method counts, close variants included: `coimmunoprecipitation` and `anti tag coimmunoprecipitation` are two.
- **A description is one observation**: one pair, one publication, one detection method, and its peptides. It comes from IntAct, from our curation, or from both independently (`evidence` says which). VH descriptions are all ours. IntAct's are kept only when an experiment observed a real interaction in a publication, by a method that shows one: no light microscopy, ChIP or genetic assays. Ours are all kept.
- **Re-reported experiments count once.** A publication that re-analyses an earlier one's experiment only adds the pairs the earlier one lacks: a pair BioPlex 2.0 and BioPlex 3.0 both report counts one publication, BioPlex 2.0. MuSIC, over BioPlex 3.0, is treated the same way.
- **Topics** are lists of human proteins kept on the client side, in a file or knowledge base, passed to tools as `accessions`, with whatever else the list records, such as a role, joined to the results by you.
- **Human proteins** are every Swiss-Prot human entry, about 20,000, including those no interaction names.
- **GO is function only**: experimental annotations of human proteins, for biological process and molecular function, with no cellular component and nothing at or below `protein binding`, since binding is what the interactions say. High-throughput evidence codes (`HTP`, `HDA`, `HMP`, `HGI`, `HEP`) weigh less than a focused experiment. A `NOT` annotation states what a protein is not involved in; the tools leave it out unless asked. `regulation of X` is not below `X` in the ontology: search for it by name.
- **Peptides are directed**: each comes from one partner of an interaction and binds the other. A peptide sequence is one node, shared by every pair it was reported for, so its evidence belongs to one source and target at a time; `peptides` and `peptide` keep them apart.
- **Taxa are current**: a virus's taxon id is NCBI's current one, even where the literature uses a retired id.

## Writing Cypher

Read the `schema` tool first: every label, property and relationship, and how their ids are made. Then:

- **Enter through `:Protein`**, the only label whose `id` is indexed, and close the filter with `WITH` before the next `MATCH`: `MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human WITH h MATCH (h)-…`. `MATCH (h:Human {id: …})` scans every human protein.
- **Close every filtered `MATCH` with `WITH`, carrying every variable its `WHERE` reads**: `WITH h, i, v WHERE …`. The engine refuses a `WHERE` on a variable its `WITH` left behind.
- **Pass values as `params`**, `$name` in the statement, rather than inlining them.
- **Return properties, not nodes.** A node comes back as its properties plus `_labels`, an edge as its properties plus `_type`, and a protein's `function` and a publication's `abstract` are long.
- **Partners without sides.** `(p)-[e:INTERACTS_WITH]-(q) WHERE q <> p` reaches every partner in one hop: the shortcut edge carries the interaction's counters and its `interaction_id`. A homodimer is a self-loop, and `q <> p` drops it.
- **Sides, when they matter.** Through `(p)<-[:INVOLVES]-(i:Interaction)-[:INVOLVES]->(q)`, each `:INVOLVES` has a `side`. In a `:VH` interaction side `a` is the human protein and side `b` the viral one; in `:HH` the order means nothing.
- **Peptide direction.** The peptide came from the partner whose `INVOLVES.side` equals the `REPORTS.source_side`, and binds the other. Without that comparison, source and target are silently mixed.
- **Viruses and families**: `(:Viral)-[:IN_TAXON]->(t:Virus)-[:PARENT]->(f:Family)`. `t.name` is the familiar name (`HBV`, `SARS-CoV-2`), `t.full_name` the scientific one. A virus with no family has no `:PARENT`.
- **GO rollup**: `(h)<-[:ANNOTATES]-(a:Annotation)-[:OF_TERM]->(:GoTerm)-[:IS_A|PART_OF*0..]->(g)`, excluding `a.qualifier STARTS WITH 'NOT'`. `*0..` keeps the annotated terms themselves as well as every term above them.
- **Full text**: `CALL db.idx.fulltext.queryNodes('Publication', $text) YIELD node, score` searches titles and abstracts.

### Well-supported interactions with no peptide yet

Golden VH interactions with a topic's proteins where no peptide is known: where to look next for one.

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

### Convergence: topic proteins reached by several families

Each family counts once a golden interaction reaches the protein; the evidence stays per interaction.

```cypher
MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
WITH h
MATCH (h)-[e:INTERACTS_WITH]-(v:Viral)
WITH h, e, v
WHERE e.n_publications >= 2 OR e.n_methods >= 2
MATCH (v)-[:IN_TAXON]->(:Virus)-[:PARENT]->(f:Family)
RETURN h.name AS human, count(DISTINCT f) AS n_families,
       collect(DISTINCT f.name) AS families
ORDER BY n_families DESC, human
```

### Human proteins two proteins both bind

What two viral proteins, or any two proteins, have in common one hop away.

```cypher
MATCH (a:Protein {id: $a})-[:INTERACTS_WITH]-(m:Human)
WITH a, m WHERE m <> a
MATCH (m)-[:INTERACTS_WITH]-(b:Protein {id: $b})
WITH m, b WHERE m <> b
RETURN m.id AS id, m.name AS name
ORDER BY name
```

## Recipes

- **A family on a topic.** `coverage` places the family among the others, against its overall reach. `vh_interactions` with the family and the topic's accessions gives the interactions, `evidence` the observations behind the ones that matter, and `publications` their abstracts. `hh_interactions` with `around` and `neighbours` show the human context; `indirect_reach` adds the targets reached through one protein in between.
- **What a family's targets do.** Take the human proteins of `vh_interactions` for the family, and pass them to `go_rollup` with a reference set as `background`, such as the topic or every human protein the family's virus reaches: each term comes with the counts an exact test needs.
- **From a word to the graph.** `search_publications` finds the papers, `publication_content` what each backs: interactions, GO annotations, function texts.
- **Drafting a topic.** `search_go_terms` finds the terms, `go_term_proteins` the proteins under them, `neighbours` the candidates the list misses. The draft goes to the user, who curates it into the topic's file.

## Worked example

*HCV NS5A binds human GPX4 (P36969), reported in PMID 12345678 by two-hybrid and by anti-bait coIP, with the peptide `PSLKATC` from NS5A sufficient for the interaction.* The values are illustrative.

```
(:Protein:Human {id:"P36969", name:"GPX4",
                 description:"Phospholipid hydroperoxide glutathione peroxidase",
                 function:"Essential antioxidant peroxidase…"})
    -[:FUNCTION_CITES]-> (:Publication {pmid:"24439385", …})
(:Protein:Viral {id:"3052230:NS5A", name:"NS5A",
                 description:"Genome polyprotein", function:"…"})
    -[:IN_TAXON]-> (:Taxon:Virus {taxon_id:3052230, name:"HCV",
                                  full_name:"Orthohepacivirus hominis"})
    -[:PARENT]->   (:Taxon:Family {taxon_id:3700683, name:"Hepaciviridae"})

(:Interaction:VH {id:"P36969|3052230:NS5A", n_descriptions:2,
                  n_publications:1, n_methods:2, n_peptides:1})
    -[:INVOLVES {side:"a"}]-> (P36969)              <- human is always side a
    -[:INVOLVES {side:"b"}]-> (3052230:NS5A)

(P36969)-[:INTERACTS_WITH {interaction_id:"P36969|3052230:NS5A", n_descriptions:2,
                           n_publications:1, n_methods:2, n_peptides:1}]->(3052230:NS5A)

(:Description {id:"D-00417", intact_id:"", stable_ids:["D-00417"],
               method_id:"MI:0018", method_name:"two hybrid"})
    -[:SUPPORTS]->     (:Interaction:VH {id:"P36969|3052230:NS5A"})
    -[:REPORTED_IN]->  (:Publication {pmid:"12345678", …})
    -[:REPORTS {source_side:"b"}]-> (:Peptide {sequence:"PSLKATC", length:7})

(:Annotation {id:"P36969|GO:0097707|24439385|IMP|UniProt|involved_in",
              qualifier:"involved_in", evidence_code:"IMP", assigned_by:"UniProt"})
    -[:ANNOTATES]->   (P36969)
    -[:OF_TERM]->     (:GoTerm {go_id:"GO:0097707", name:"ferroptosis"})
    -[:REPORTED_IN]-> (:Publication {pmid:"24439385", …})
```

`source_side: "b"` is what makes the peptide directed: side `b` is NS5A, so the peptide is *from* NS5A and *binds* GPX4. The coIP is a second description of the same pair in the same paper: it adds one `:Description` and one method, so the interaction has two descriptions, one publication and two methods, which makes it golden. Had it observed NS5A on another HCV strain, it would still support the same interaction; `evidence` gives the UniProt entry each VH description observed.

Publication 24439385 backs both GPX4's function text and its ferroptosis annotation: one node, reached from both.
