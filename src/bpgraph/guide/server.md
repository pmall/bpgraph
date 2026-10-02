bpgraph: protein–protein interactions, human–human (HH) and virus–human (VH), each backed by the publications that report it, abstracts included. Human proteins are all of Swiss-Prot, with UniProt function text and experimental GO annotations of process and function. A viral protein is curated, keyed by its virus's NCBI taxon id and its name, e.g. `HBx` of HBV (10407), pooled over its strains.

- Call `schema` first: the graph's nodes and relationships, and the rules for Cypher that runs fast. Then query with `cypher`.
- Ask the graph in patterns: one query can go from a virus through its interactions and their descriptions to the publications' abstracts, or through a protein in between. Prefer one pattern to a chain of small queries.
- A name that matches nothing returns no rows, not an error: check a name exists before reading an empty result as an absence.
- Evidence is per interaction: never add counters across viral proteins or viruses. The counters are `n_publications`, `n_methods` (distinct PSI-MI methods), `n_descriptions` (observations) and `n_peptides`.
- Results are tab-separated tables, their first line counting the rows.
- A result over `max_tokens` (25,000 by default) is refused with its size: narrow the question, or raise `max_tokens`.
- Counts first, rows next, text last: read abstracts and function text once a question is narrowed down. The text is where the meaning is.
- Sequences are outside the graph, in vaults: `human_sequences`, `viral_sequences`, and `observed_sequences` for the exact mature protein a VH description observed.
