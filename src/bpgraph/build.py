"""Running a build: load into staging, validate, swap over the live graph.

The live graph is never written to. A run builds beside it and publishes with a
single `RENAME`, so a bad export cannot land on something people are querying.
"""

from dataclasses import dataclass

from falkordb import FalkorDB

from bpgraph import api, schema
from bpgraph.client import GraphWriter
from bpgraph.config import Config
from bpgraph.models import Export
from bpgraph.schema import ConstraintRow


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What a run wrote, and the constraint states it passed."""

    graph: str
    counts: dict[str, int]
    constraints: list[ConstraintRow]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _reset(db: FalkorDB, name: str) -> None:
    if name in db.list_graphs():
        db.select_graph(name).delete()


def _load(writer: GraphWriter, export: Export) -> dict[str, int]:
    """Every write of a run, in dependency order.

    Order matters twice over: a relationship can only be created once both its
    endpoints exist, and the two derivations at the end can only run once
    everything they read is in place.
    """
    counts = {
        "proteins": api.write_proteins(writer, export.proteins),
        "taxa": api.write_taxa(writer, export.taxa),
        "taxon_links": api.write_taxon_links(writer, export.taxon_links),
        "topics": api.write_topics(writer, export.topics),
        "involvements": api.write_involvements(writer, export.involvements),
        "publications": api.write_publications(writer, export.publications),
        "methods": api.write_methods(writer, export.methods),
        "peptides": api.write_peptides(writer, export.descriptions),
        "interactions": api.write_interactions(writer, export.descriptions),
        "descriptions": api.write_descriptions(writer, export.descriptions),
        "reported_peptides": api.write_reported_peptides(writer, export.descriptions),
        "go_terms": api.write_go_terms(writer, export.go_terms),
        "go_edges": api.write_go_edges(writer, export.go_edges),
        "go_annotations": api.write_go_annotations(writer, export.go_annotations),
    }
    api.link_proteins_to_taxa(writer)
    api.update_interaction_counters(writer)
    return counts


def build(db: FalkorDB, export: Export, config: Config) -> BuildReport:
    """Build the export into staging and publish it. Returns what was written.

    Raises `ConstraintsNotSatisfied` if the export violates a key, leaving the
    live graph untouched and dropping the staging graph.
    """
    _reset(db, config.staging_graph)
    staging = db.select_graph(config.staging_graph)

    # Indexes before the data so every MATCH during the load is index-backed;
    # constraints after it, so a duplicate shows up as a FAILED constraint.
    schema.create_indexes(staging)
    counts = _load(GraphWriter(staging), export)
    schema.create_constraints(staging)

    try:
        constraints = schema.validate_constraints(staging)
    except schema.ConstraintsNotSatisfied:
        _reset(db, config.staging_graph)
        raise

    db.connection.rename(config.staging_graph, config.live_graph)
    return BuildReport(graph=config.live_graph, counts=counts, constraints=constraints)
