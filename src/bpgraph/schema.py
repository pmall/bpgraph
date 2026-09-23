"""Index and constraint DDL, and the validation gate a run must pass.

Indexes go in **before** the data, so every `MATCH` a build performs is
index-backed. Constraints go in **after**, because that is what makes them a
gate: FalkorDB does not reject a constraint created over violating rows, it
parks it in state `FAILED`, which is exactly the signal a run needs.
"""

import time
from typing import TypedDict, cast

from falkordb.graph import Graph


class ConstraintRow(TypedDict):
    """One row of `CALL db.constraints()`, typed at the client boundary."""

    type: str
    label: str
    properties: list[str]
    entitytype: str
    status: str


UNIQUE_CONSTRAINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Protein", ("id",)),
    ("Protein", ("accession", "start", "stop")),
    ("Taxon", ("taxon_id",)),
    ("Topic", ("name",)),
    ("GoTerm", ("go_id",)),
    ("Publication", ("pmid",)),
    ("Method", ("psimi_id",)),
    ("Interaction", ("id",)),
    ("Description", ("id",)),
    ("Peptide", ("sequence",)),
)
"""Both protein constraints are needed. The composite one only applies to nodes
carrying all three properties, and catches an id that disagrees with its
coordinates; the id one catches everything else."""

EXTRA_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Protein", ("name",)),
    ("Protein", ("taxon_id",)),
    ("Taxon", ("rank",)),
    ("GoTerm", ("namespace",)),
    ("Peptide", ("length",)),
)
"""Queried but not constrained. Constrained properties are indexed already."""

FULLTEXT_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Publication", ("title", "abstract")),
)

OPERATIONAL = "OPERATIONAL"
BUILDING = frozenset({"PENDING", "UNDER CONSTRUCTION"})
"""The two statuses a constraint reports while it is still being applied.

Both come out of the running module — `GRAPH.CONSTRAINT CREATE` answers
`PENDING` and `CALL db.constraints()` then reports `UNDER CONSTRUCTION` until
the scan finishes. Treating either as a verdict fails a sound export."""


class ConstraintsNotSatisfied(RuntimeError):
    """A constraint failed to build, so the export violated one of its keys."""


def create_indexes(graph: Graph) -> None:
    """Call before loading. Indexing a property twice is an error, so the
    constrained properties are indexed here and not again by the constraints."""
    for label, properties in (*UNIQUE_CONSTRAINTS, *EXTRA_INDEXES):
        graph.create_node_range_index(label, *properties)
    for label, fields in FULLTEXT_INDEXES:
        graph.create_node_fulltext_index(label, *fields)


def create_constraints(graph: Graph) -> None:
    """Call after loading. Constraints are applied asynchronously — poll with
    `validate_constraints`, which is where the wait belongs."""
    for label, properties in UNIQUE_CONSTRAINTS:
        graph.create_node_unique_constraint(label, *properties)


def _constraints(graph: Graph) -> list[ConstraintRow]:
    return cast(list[ConstraintRow], graph.list_constraints())


def validate_constraints(graph: Graph, timeout: float = 60.0) -> list[ConstraintRow]:
    """Wait for every constraint to settle, then insist all are operational.

    Raises `ConstraintsNotSatisfied` naming the ones that failed, so the caller
    can drop the staging graph rather than publish a corrupt export.
    """
    deadline = time.monotonic() + timeout
    report = _constraints(graph)
    while any(row["status"] in BUILDING for row in report):
        if time.monotonic() > deadline:
            raise ConstraintsNotSatisfied(
                f"constraints still building after {timeout}s"
            )
        time.sleep(0.2)
        report = _constraints(graph)

    failed = [row for row in report if row["status"] != OPERATIONAL]
    if failed:
        named = ", ".join(f"{row['label']}{row['properties']}" for row in failed)
        raise ConstraintsNotSatisfied(f"duplicate keys in the export: {named}")
    if len(report) != len(UNIQUE_CONSTRAINTS):
        raise ConstraintsNotSatisfied(
            f"expected {len(UNIQUE_CONSTRAINTS)} constraints, found {len(report)}"
        )
    return report
