"""Beyond the predefined queries: the schema, and read-only Cypher."""

from pathlib import Path
from typing import Annotated

from pydantic import Field

from bpgraph.api.base import Backend, Rows, whole
from bpgraph.query import Row
from bpgraph.schema import EXTRA_INDEXES, FULLTEXT_INDEXES, UNIQUE_CONSTRAINTS
from bpgraph.shape import NODE_PROPERTIES, RELATIONSHIPS, SUBLABELS

TYPES = {"String": "str", "Integer": "int", "List": "list", "Boolean": "bool"}

NOTES = {
    "Protein": "A `:Human` id is a Swiss-Prot accession, a `:Viral` id "
    "`<virus taxon id>:<name>`. `description` is UniProt's name, `function` "
    "its function text.",
    "Virus": "`name` is the familiar name (`HBV`), `full_name` the scientific one.",
    "Publication": "`year` is 0 when PubMed gives none.",
    "Interaction": "`:HH` or `:VH`, id `<side a>|<side b>`. The counters are the "
    "evidence: distinct publications, distinct PSI-MI methods, observations, "
    "distinct peptides.",
    "Description": "One observation: one pair, one publication, one method. "
    "`intact_id` is empty unless IntAct's; `stable_ids` lists our curated rows.",
    "Annotation": "An experimental GO annotation of a human protein; a "
    "`qualifier` starting `NOT` negates it.",
    "GoTerm": "`namespace` is `biological_process` or `molecular_function`.",
    "INVOLVES": "`side` is `a` or `b`; in `:VH`, `a` is the human protein.",
    "INTERACTS_WITH": "From side `a` to side `b`, one per interaction, with its "
    "counters: match it undirected.",
    "REPORTS": "`source_side` is the side the peptide comes from.",
    "FUNCTION_CITES": "The publications a protein's function text cites.",
    "IS_A": "Points up the ontology.",
    "PART_OF": "Points up the ontology.",
}

GUIDE = (Path(__file__).parents[1] / "guide" / "cypher.md").read_text()


def _labels(label: str) -> str:
    for base, (one, other) in SUBLABELS.items():
        if label in (one, other):
            return f":{base}:{label}"
        if label == base:
            return f":{base} (:{one} or :{other})"
    return f":{label}"


def _describe() -> str:
    keys = {label: props for label, props in UNIQUE_CONSTRAINTS}
    indexed = {label: props for label, props in EXTRA_INDEXES}
    fulltext = {label: props for label, props in FULLTEXT_INDEXES}

    def tag(label: str, prop: str) -> str:
        bases = [label, *(b for b, pair in SUBLABELS.items() if label in pair)]
        if any(prop in keys.get(b, ()) for b in bases):
            return " key"
        if any(prop in indexed.get(b, ()) for b in bases):
            return " indexed"
        if any(prop in fulltext.get(b, ()) for b in bases):
            return " full-text"
        return ""

    lines = ["## Nodes", ""]
    for label, properties in NODE_PROPERTIES.items():
        props = ", ".join(
            f"{p} {TYPES.get(t, t)}{tag(label, p)}" for p, t in properties.items()
        )
        note = f" {NOTES[label]}" if label in NOTES else ""
        lines.append(f"- `{_labels(label)}`: {props}.{note}")
    lines += ["", "## Relationships", ""]
    for kind, source, target, properties in RELATIONSHIPS:
        props = f" {{{', '.join(properties)}}}" if properties else ""
        sources = " or ".join(f":{s}" for s in source.split("|"))
        note = f" {NOTES[kind]}" if kind in NOTES else ""
        lines.append(f"- `({sources})-[:{kind}{props}]->(:{target})`.{note}")
    return "\n".join(lines)


def schema(backend: Backend) -> str:
    """The graph's labels, properties and relationships, with what is indexed,
    then the rules for Cypher that runs fast and worked examples. Read it
    before writing `cypher`."""
    return f"{_describe()}\n\n{GUIDE}"


def cypher(
    backend: Backend,
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="One read-only Cypher statement, values as `$name`.",
        ),
    ],
    params: Annotated[
        dict[str, object] | None, Field(description="The values of `$name`.")
    ] = None,
) -> Rows[Row]:
    """Run one read-only Cypher statement on the live graph, for what no
    predefined tool answers. Read `schema` first: it gives the structure and
    the rules for Cypher that runs fast."""
    return whole(backend.rows(query, **(params or {})))
