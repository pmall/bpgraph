"""The docs against the code. `shape.py` is the graph's shape, which the audit
checks on the live graph: the builder's schema, docs/schema.md, and the
client's, guide/schema.md, must name exactly what it holds, and the invariants
of docs/schema.md must be the ones the audit checks."""

import re
from pathlib import Path

from bpgraph import audit, shape

GRAPH = Path(__file__).resolve().parents[1]
SCHEMA = (GRAPH / "docs" / "schema.md").read_text()
GUIDE = (GRAPH / "src" / "bpgraph" / "guide" / "schema.md").read_text()
DEVELOPMENT = (GRAPH / "docs" / "development.md").read_text()

NAME = re.compile(r":([A-Z][A-Za-z_]*)")
"""A label or a relationship type, as Cypher writes it: `:Human`, `:INVOLVES`."""

PATTERN = re.compile(r"(?=\(:(\w+)\)-\[:([\w|]+)[^\]]*\]->\(:(\w+)\))")
"""A relationship between two labels, `(:A)-[:TYPE]->(:B)`, chained ones
included; `:IS_A|PART_OF` is two types."""

EDGE_PROPERTIES = re.compile(r"\[:(\w+) \{([^}]*)\}\]")
TABLE_NAME = re.compile(r"^\|\s*`(\w+)`", re.M)
INVARIANT = re.compile(r"^\|\s*([A-Z]\d+)\s*\|", re.M)
PROPERTY = re.compile(r"`([a-z_]+)`")

LABELS = {
    *shape.NODE_PROPERTIES,
    *shape.SUBLABELS,
    *(label for pair in shape.SUBLABELS.values() for label in pair),
}
TYPES = {kind for kind, *_ in shape.RELATIONSHIPS}
EDGES = {
    (kind, source, target)
    for kind, sources, target, _ in shape.RELATIONSHIPS
    for source in sources.split("|")
}


def section(text: str, heading: str) -> str:
    """A `## ` section of a doc, without its heading."""
    start = re.search(rf"^## {heading}\b.*$", text, re.M)
    assert start is not None, f"no section {heading}"
    end = re.search(r"^## ", text[start.end() :], re.M)
    return text[start.end() : start.end() + end.start() if end else len(text)]


def described(labels: list[str]) -> set[str]:
    """The labels with properties that labels named together stand for: each
    its own, and a base label without any its sublabels, unless one is named."""
    named = set(labels)
    return {
        each
        for label in labels
        for each in (
            (label,)
            if label in shape.NODE_PROPERTIES
            else ()
            if named & set(shape.SUBLABELS.get(label, ()))
            else shape.SUBLABELS.get(label, ())
        )
        if each in shape.NODE_PROPERTIES
    }


def properties(labels: set[str]) -> set[str]:
    return {name for label in labels for name in shape.NODE_PROPERTIES[label]}


def edges(text: str) -> set[tuple[str, str, str]]:
    return {
        (kind, source, target)
        for source, kinds, target in PATTERN.findall(text)
        for kind in kinds.split("|")
    }


def test_the_schema_lists_each_label_s_properties() -> None:
    covered: set[str] = set()
    for part in re.split(r"^### ", section(SCHEMA, "Nodes"), flags=re.M)[1:]:
        heading, _, body = part.partition("\n")
        labels = described(NAME.findall(heading))
        assert set(TABLE_NAME.findall(body)) == properties(labels), heading
        covered |= labels
    assert covered == set(shape.NODE_PROPERTIES)


def test_the_schema_s_relationships_are_the_graph_s() -> None:
    relationships = section(SCHEMA, "Relationships")
    assert edges(relationships) == EDGES
    for kind, _, _, carried in shape.RELATIONSHIPS:
        if carried:
            listed = relationships.partition(f"### `:{kind}`")[2]
            assert set(TABLE_NAME.findall(listed)) == set(carried), kind


def test_the_guide_names_each_label_s_properties() -> None:
    covered: set[str] = set()
    for line in section(GUIDE, "Nodes").splitlines():
        if not line.startswith("- `:"):
            continue
        labels = described(NAME.findall(line.split("`")[1]))
        assert properties(labels) <= set(PROPERTY.findall(line)), line
        covered |= labels
    assert covered == set(shape.NODE_PROPERTIES)


def test_the_guide_s_relationships_are_the_graph_s() -> None:
    relationships = section(GUIDE, "Relationships")
    assert edges(relationships) == EDGES
    shown = {
        kind: {name.strip() for name in listed.split(",")}
        for kind, listed in EDGE_PROPERTIES.findall(relationships)
    }
    for kind, _, _, carried in shape.RELATIONSHIPS:
        if carried:
            assert shown.get(kind) == set(carried), kind


def test_the_docs_name_no_label_or_type_the_graph_lacks() -> None:
    for doc in (SCHEMA, GUIDE):
        assert set(NAME.findall(doc)) <= LABELS | TYPES


def test_the_schema_s_invariants_are_the_audit_s() -> None:
    documented = set(INVARIANT.findall(section(SCHEMA, "Invariants")))
    checked = {check.invariant for check in audit.CHECKS}
    assert documented == checked - {"E1"}
    assert "`E1`" in DEVELOPMENT
