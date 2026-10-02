bpgraph: protein–protein interactions, human–human (HH) and virus–human (VH), each backed by the publications that report it, abstracts included. Human proteins are all of Swiss-Prot, with UniProt function text and experimental GO annotations of process and function. A viral protein is curated, e.g. `10407:HBx`, HBx of HBV pooled over its strains.

- Use the predefined tools first. For anything else, call `schema` for the graph's structure and the rules for Cypher, then query with `cypher`.
- Evidence is per interaction: never add counters across viral proteins or viruses. The counters are `n_publications`, `n_methods` (distinct PSI-MI methods), `n_descriptions` (observations) and `n_peptides`.
- Results are tab-separated tables. Their first line counts the rows: `100 of 15602 rows` means `limit` kept 100. `limit: 1` gives a count for one row's cost.
- A result over `max_tokens` (25,000 by default) is refused with its size: narrow the question, or raise `max_tokens`.
- An unknown name is an error naming the closest known ones.
- Counts first, rows next, text last: read abstracts (`publications` with `abstracts: true`) and function text once a question is narrowed down. The text is where the meaning is.
