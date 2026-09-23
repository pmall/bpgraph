"""Batched writers. The only code in bpgraph that emits Cypher."""

from bpgraph.api.annotations import write_go_annotations, write_go_edges, write_go_terms
from bpgraph.api.interactions import (
    update_interaction_counters,
    write_descriptions,
    write_interactions,
    write_methods,
    write_peptides,
    write_publications,
    write_reported_peptides,
)
from bpgraph.api.proteins import write_proteins
from bpgraph.api.taxonomy import link_proteins_to_taxa, write_taxa, write_taxon_links
from bpgraph.api.topics import write_involvements, write_topics

__all__ = [
    "link_proteins_to_taxa",
    "update_interaction_counters",
    "write_descriptions",
    "write_go_annotations",
    "write_go_edges",
    "write_go_terms",
    "write_involvements",
    "write_interactions",
    "write_methods",
    "write_peptides",
    "write_proteins",
    "write_publications",
    "write_reported_peptides",
    "write_taxa",
    "write_taxon_links",
    "write_topics",
]
