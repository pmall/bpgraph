"""Batched writers. Every write statement in bpgraph lives here."""

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
from bpgraph.api.proteins import write_function_citations, write_proteins
from bpgraph.api.taxonomy import (
    write_families,
    write_memberships,
    write_taxon_links,
    write_viruses,
)
from bpgraph.api.topics import write_involvements, write_topics

__all__ = [
    "update_interaction_counters",
    "write_descriptions",
    "write_families",
    "write_function_citations",
    "write_go_annotations",
    "write_go_edges",
    "write_go_terms",
    "write_involvements",
    "write_interactions",
    "write_memberships",
    "write_methods",
    "write_peptides",
    "write_proteins",
    "write_publications",
    "write_reported_peptides",
    "write_taxon_links",
    "write_topics",
    "write_viruses",
]
