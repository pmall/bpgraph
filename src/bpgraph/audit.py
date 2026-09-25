"""Auditing a built graph against docs/schema.md.

The constraint gate in `schema.py` only proves that keys are unique. Everything
else the schema promises — that no property is missing or mistyped, that a
`:Protein` is human or viral and never both, that a derived id agrees with the
values it was derived from, that each side of a description was observed on an
entry of that side's protein, that `:VH` puts the human on side `a`, that the
counters match what they count — is unchecked at build time, because FalkorDB
has no schema to check it against.

**The expectations below are restated from docs/schema.md by hand, and that is
the point.** Deriving them from the models or the writers would only prove the
code agrees with itself; written out separately, they disagree when either side
drifts, and that disagreement is the finding.

Every check is one read-only query that returns the rows *breaking* its rule,
so an empty result is a pass. Queries end in `RETURN` — the runner appends the
limit.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from falkordb.graph import Graph

EXAMPLES = 5

GO_ROOTS = ("GO:0008150", "GO:0003674", "GO:0005575")
"""The three namespace roots: biological process, molecular function,
cellular component. Nothing sits above them, so they are the one place the
ancestor closure is allowed to stop."""

NODE_PROPERTIES: Mapping[str, Mapping[str, str]] = {
    "Protein": {
        "id": "String",
        "name": "String",
        "description": "String",
        "function": "String",
    },
    "Entry": {
        "accession": "String",
        "taxon_id": "Integer",
        "taxon_name": "String",
        "description": "String",
    },
    "Virus": {"taxon_id": "Integer", "name": "String", "full_name": "String"},
    "Family": {"taxon_id": "Integer", "name": "String"},
    "Topic": {"name": "String"},
    "Publication": {
        "pmid": "String",
        "title": "String",
        "abstract": "String",
        "journal": "String",
        "year": "Integer",
        "authors": "List",
    },
    "Method": {"psimi_id": "String", "name": "String"},
    "Interaction": {
        "id": "String",
        "n_descriptions": "Integer",
        "n_publications": "Integer",
        "n_methods": "Integer",
        "n_peptides": "Integer",
    },
    "Description": {"id": "String"},
    "Peptide": {"sequence": "String", "length": "Integer"},
    "GoTerm": {
        "go_id": "String",
        "name": "String",
        "namespace": "String",
        "obsolete": "Boolean",
    },
}
"""Every property schema.md lists, and the type FalkorDB should report for it.

A missing property types as `Null`, so one test catches both absence and drift.
`:Taxon` is checked through its two sublabels, whose properties differ.
"""

SUBLABELS: Mapping[str, tuple[str, str]] = {
    "Protein": ("Human", "Viral"),
    "Interaction": ("HH", "VH"),
    "Taxon": ("Virus", "Family"),
}
"""Labels that carry a type: exactly one of the pair, beside the base label."""

RELATIONSHIPS: tuple[tuple[str, str, str, tuple[str, ...] | None], ...] = (
    ("INVOLVES", "Interaction", "Protein", ("side",)),
    ("ON_ENTRY", "Protein", "Entry", None),
    ("SUPPORTS", "Description", "Interaction", ()),
    ("OBSERVED_ON", "Description", "Entry", ("side",)),
    ("REPORTED_IN", "Description", "Publication", ()),
    ("DETECTED_BY", "Description", "Method", ()),
    ("REPORTS", "Description", "Peptide", ("source_side",)),
    ("IN_TAXON", "Viral", "Virus", ()),
    ("PARENT", "Virus", "Family", ()),
    ("INVOLVED_IN", "Human", "Topic", None),
    (
        "ANNOTATED_WITH",
        "Human",
        "GoTerm",
        ("evidence_code", "assigned_by", "qualifier"),
    ),
    ("IS_A", "GoTerm", "GoTerm", ()),
    ("PART_OF", "GoTerm", "GoTerm", ()),
)
"""Type, the labels it must join, and its properties. `None` means they vary:
by topic for `INVOLVED_IN`, checked by `TOPIC_PROPERTIES`, and by the protein's
kind for `ON_ENTRY`, checked by the invariants."""

TOPIC_PROPERTIES: Mapping[str, tuple[str, ...]] = {
    "ferroptosis": ("role",),
}
"""Every topic, and the properties its `:INVOLVED_IN` edges carry."""


@dataclass(frozen=True, slots=True)
class Check:
    """One rule, and the query that finds what breaks it."""

    name: str
    rule: str
    cypher: str


@dataclass(frozen=True, slots=True)
class Finding:
    """A check that came back with rows. `examples` is capped, so a finding
    says something is wrong, never how much of it there is."""

    check: Check
    columns: list[str]
    examples: list[list[object]]


def _node_shape(label: str, properties: Mapping[str, str]) -> Check:
    """Every listed property present and of the right type, and nothing else."""
    tests = " OR ".join(
        f"typeOf(n.{name}) <> '{kind}'" for name, kind in properties.items()
    )
    return Check(
        name=f"{label}.properties",
        rule=f"{label} carries exactly {', '.join(properties)}",
        cypher=(
            f"MATCH (n:{label})\n"
            f"WHERE {tests} OR size(keys(n)) <> {len(properties)}\n"
            "RETURN ID(n) AS node, keys(n) AS keys"
        ),
    )


def _sublabel(base: str, options: tuple[str, str]) -> Check:
    allowed = ", ".join(f"'{option}'" for option in options)
    return Check(
        name=f"{base}.labels",
        rule=f"{base} carries exactly one of {' | '.join(options)}",
        cypher=(
            f"MATCH (n:{base})\n"
            f"WITH n, [l IN labels(n) WHERE l <> '{base}'] AS extra\n"
            f"WHERE size(extra) <> 1 OR NOT extra[0] IN [{allowed}]\n"
            "RETURN ID(n) AS node, labels(n) AS labels"
        ),
    )


def _edge_shape(
    kind: str, source: str, target: str, properties: tuple[str, ...] | None
) -> Check:
    """The labels an edge joins, and the properties it carries."""
    tests = [f"NOT a:{source}", f"NOT b:{target}"]
    rule = f"(:{source})-[:{kind}]->(:{target})"
    if properties is not None:
        tests += [f"typeOf(r.{name}) = 'Null'" for name in properties]
        tests.append(f"size(keys(r)) <> {len(properties)}")
        rule += f" carrying {', '.join(properties) or 'no properties'}"
    return Check(
        name=f"{kind}.shape",
        rule=rule,
        cypher=(
            f"MATCH (a)-[r:{kind}]->(b)\n"
            f"WHERE {' OR '.join(tests)}\n"
            "RETURN ID(r) AS edge, labels(a) AS source, labels(b) AS target,\n"
            "       keys(r) AS keys"
        ),
    )


def _topic_shape(topic: str, properties: tuple[str, ...]) -> Check:
    """The properties one topic's edges carry, which no other topic shares."""
    tests = [f"typeOf(r.{name}) = 'Null'" for name in properties]
    tests.append(f"size(keys(r)) <> {len(properties)}")
    return Check(
        name=f"INVOLVED_IN.{topic}",
        rule=f"{topic} involvements carry {', '.join(properties)}",
        cypher=(
            f"MATCH (p)-[r:INVOLVED_IN]->(:Topic {{name: '{topic}'}})\n"
            f"WHERE {' OR '.join(tests)}\n"
            "RETURN p.id AS id, keys(r) AS keys"
        ),
    )


KNOWN_LABELS = (*NODE_PROPERTIES, "Taxon")

INVARIANTS: tuple[Check, ...] = (
    Check(
        "graph.labels",
        "every node carries one of the labels schema.md defines",
        "MATCH (n)\n"
        f"WHERE NOT ({' OR '.join(f'n:{label}' for label in KNOWN_LABELS)})\n"
        "RETURN ID(n) AS node, labels(n) AS labels",
    ),
    Check(
        "Human.entry",
        "a human protein is on exactly one entry, its id, by a bare ON_ENTRY",
        "MATCH (p:Human)\n"
        "WITH p, [(p)-[r:ON_ENTRY]->(e) | [e.accession, size(keys(r))]] AS entries\n"
        "WHERE size(entries) <> 1 OR entries[0][0] <> p.id OR entries[0][1] <> 0\n"
        "RETURN p.id AS id, entries",
    ),
    Check(
        "Viral.entries",
        "a viral protein is on at least one entry, each edge a span 1 <= start <= stop",
        "MATCH (p:Viral)\n"
        "OPTIONAL MATCH (p)-[r:ON_ENTRY]->(:Entry)\n"
        "WITH p, r\n"
        "WHERE r IS NULL OR size(keys(r)) <> 2\n"
        "   OR typeOf(r.start) <> 'Integer' OR typeOf(r.stop) <> 'Integer'\n"
        "   OR r.start < 1 OR r.stop < r.start\n"
        "RETURN p.id AS id, r.start AS start, r.stop AS stop",
    ),
    Check(
        "Viral.id",
        "a viral id is its curated virus's taxon id and its name",
        "MATCH (p:Viral)-[:IN_TAXON]->(v:Virus)\n"
        "WHERE p.id <> toString(v.taxon_id) + ':' + p.name\n"
        "RETURN p.id AS id, v.taxon_id AS virus, p.name AS name",
    ),
    Check(
        "Entry.proteins",
        "every entry carries a protein, and never both a human and a viral one",
        "MATCH (e:Entry)\n"
        "WITH e, size([(e)<-[:ON_ENTRY]-(h:Human) | h]) AS human,\n"
        "        size([(e)<-[:ON_ENTRY]-(v:Viral) | v]) AS viral\n"
        "WHERE human + viral = 0 OR (human > 0 AND viral > 0)\n"
        "RETURN e.accession AS accession, human, viral",
    ),
    Check(
        "Entry.human_taxon",
        "a human protein's entry is taxon 9606",
        "MATCH (:Human)-[:ON_ENTRY]->(e:Entry)\n"
        "WHERE e.taxon_id <> 9606\n"
        "RETURN e.accession AS accession, e.taxon_id AS taxon_id",
    ),
    Check(
        "Interaction.slots",
        "two INVOLVES edges, one side 'a' and one side 'b'",
        "MATCH (i:Interaction)\n"
        "WITH i, [(i)-[r:INVOLVES]->() | r.side] AS sides\n"
        "WHERE size(sides) <> 2 OR NOT 'a' IN sides OR NOT 'b' IN sides\n"
        "RETURN i.id AS id, sides",
    ),
    Check(
        "Interaction.id",
        "the id joins its two protein ids in slot order",
        "MATCH (i:Interaction)-[:INVOLVES {side: 'a'}]->(a:Protein)\n"
        "MATCH (i)-[:INVOLVES {side: 'b'}]->(b:Protein)\n"
        "WHERE i.id <> a.id + '|' + b.id\n"
        "RETURN i.id AS id, a.id + '|' + b.id AS derived",
    ),
    Check(
        "VH.slots",
        "a VH interaction puts the human on side 'a' and the virus on side 'b'",
        "MATCH (i:VH)-[r:INVOLVES]->(p:Protein)\n"
        "WHERE (r.side = 'a' AND NOT p:Human) OR (r.side = 'b' AND NOT p:Viral)\n"
        "RETURN i.id AS id, r.side AS side, labels(p) AS partner",
    ),
    Check(
        "HH.slots",
        "an HH interaction joins two human proteins, side 'a' sorting first",
        "MATCH (i:HH)-[:INVOLVES {side: 'a'}]->(a:Protein)\n"
        "MATCH (i)-[:INVOLVES {side: 'b'}]->(b:Protein)\n"
        "WHERE NOT a:Human OR NOT b:Human OR a.id > b.id\n"
        "RETURN i.id AS id, a.id AS side_a, b.id AS side_b",
    ),
    Check(
        "Description.evidence",
        "one interaction, one publication and one method behind every description",
        "MATCH (d:Description)\n"
        "WITH d, size([(d)-[:SUPPORTS]->() | 1]) AS claims,\n"
        "        size([(d)-[:REPORTED_IN]->() | 1]) AS papers,\n"
        "        size([(d)-[:DETECTED_BY]->() | 1]) AS methods\n"
        "WHERE claims <> 1 OR papers <> 1 OR methods <> 1\n"
        "RETURN d.id AS id, claims, papers, methods",
    ),
    Check(
        "Description.observed_on",
        "a description names the entry each side was seen on, an entry of that "
        "side's protein",
        "MATCH (d:Description)-[:SUPPORTS]->(i:Interaction)\n"
        "WITH d, i, [(d)-[o:OBSERVED_ON]->() | o.side] AS sides\n"
        "OPTIONAL MATCH (d)-[o:OBSERVED_ON]->(e:Entry)\n"
        "OPTIONAL MATCH (i)-[r:INVOLVES {side: o.side}]->(p:Protein)\n"
        "WITH d, sides, o, e, p\n"
        "WHERE size(sides) <> 2 OR NOT 'a' IN sides OR NOT 'b' IN sides\n"
        "   OR p IS NULL OR NOT (p)-[:ON_ENTRY]->(e)\n"
        "RETURN d.id AS id, sides, e.accession AS entry, p.id AS protein",
    ),
    Check(
        "REPORTS.source_side",
        "a reported peptide names a slot of its description's interaction",
        "MATCH (d:Description)-[r:REPORTS]->(:Peptide)\n"
        "WHERE NOT r.source_side IN ['a', 'b']\n"
        "RETURN d.id AS id, r.source_side AS source_side",
    ),
    Check(
        "Topic.documented",
        "every topic is one schema.md documents",
        "MATCH (t:Topic)\n"
        f"WHERE NOT t.name IN {list(TOPIC_PROPERTIES)}\n"
        "RETURN t.name AS topic",
    ),
    Check(
        "Interaction.counters",
        "the counters equal what they count",
        "MATCH (i:Interaction)<-[:SUPPORTS]-(d:Description)\n"
        "OPTIONAL MATCH (d)-[:REPORTED_IN]->(b:Publication)\n"
        "OPTIONAL MATCH (d)-[:DETECTED_BY]->(m:Method)\n"
        "OPTIONAL MATCH (d)-[:REPORTS]->(x:Peptide)\n"
        "WITH i, count(DISTINCT d) AS descriptions,\n"
        "        count(DISTINCT b) AS publications,\n"
        "        count(DISTINCT m) AS methods, count(DISTINCT x) AS peptides\n"
        "WHERE i.n_descriptions <> descriptions OR i.n_publications <> publications\n"
        "   OR i.n_methods <> methods OR i.n_peptides <> peptides\n"
        "RETURN i.id AS id, descriptions, publications, methods, peptides",
    ),
    Check(
        "Interaction.supported",
        "no interaction without a description behind it",
        "MATCH (i:Interaction)\n"
        "WHERE NOT (i)<-[:SUPPORTS]-(:Description)\n"
        "RETURN i.id AS id",
    ),
    Check(
        "Viral.taxon",
        "a viral protein has one IN_TAXON edge",
        "MATCH (p:Viral)\n"
        "WITH p, [(p)-[:IN_TAXON]->(t) | t.taxon_id] AS taxa\n"
        "WHERE size(taxa) <> 1\n"
        "RETURN p.id AS id, taxa",
    ),
    Check(
        "Human.taxon",
        "a human protein gets no Taxon node",
        "MATCH (p:Human)-[:IN_TAXON]->()\nRETURN p.id AS id",
    ),
    Check(
        "Taxon.parent",
        "a virus has at most one family",
        "MATCH (t:Virus)\n"
        "WITH t, [(t)-[:PARENT]->(p) | p.taxon_id] AS parents\n"
        "WHERE size(parents) > 1\n"
        "RETURN t.taxon_id AS taxon_id, parents",
    ),
    Check(
        "Taxon.used",
        "every virus has a protein, and every family a virus",
        "MATCH (t:Taxon)\n"
        "WHERE (t:Virus AND NOT (t)<-[:IN_TAXON]-(:Viral))\n"
        "   OR (t:Family AND NOT (t)<-[:PARENT]-(:Virus))\n"
        "RETURN t.taxon_id AS taxon_id, t.name AS name",
    ),
    Check(
        "GoTerm.ancestors",
        "every term sits under a parent, up to a namespace root",
        "MATCH (t:GoTerm)\n"
        "WHERE NOT (t)-[:IS_A|PART_OF]->(:GoTerm)\n"
        "  AND NOT t.obsolete\n"
        f"  AND NOT t.go_id IN {list(GO_ROOTS)}\n"
        "RETURN t.go_id AS go_id, t.name AS name",
    ),
    Check(
        "GoTerm.reached",
        "every term is annotated, or lies above one that is",
        "MATCH (t:GoTerm)\n"
        "WHERE NOT (t)<-[:IS_A|PART_OF*0..]-(:GoTerm)<-[:ANNOTATED_WITH]-(:Protein)\n"
        "RETURN t.go_id AS go_id, t.name AS name",
    ),
    Check(
        "Peptide.sequence",
        "length is the residue count, and residues are upper case",
        "MATCH (x:Peptide)\n"
        "WHERE x.length <> size(x.sequence) OR x.length < 1\n"
        "   OR toUpper(x.sequence) <> x.sequence\n"
        "RETURN x.sequence AS sequence, x.length AS length",
    ),
    Check(
        "Publication.cited",
        "every publication backs at least one description",
        "MATCH (b:Publication)\n"
        "WHERE NOT (b)<-[:REPORTED_IN]-(:Description)\n"
        "RETURN b.pmid AS pmid",
    ),
    Check(
        "Method.used",
        "every method detected at least one description",
        "MATCH (m:Method)\n"
        "WHERE NOT (m)<-[:DETECTED_BY]-(:Description)\n"
        "RETURN m.psimi_id AS psimi_id",
    ),
    Check(
        "Peptide.reported",
        "every peptide is reported by at least one description",
        "MATCH (x:Peptide)\n"
        "WHERE NOT (x)<-[:REPORTS]-(:Description)\n"
        "RETURN x.sequence AS sequence",
    ),
)

CHECKS: tuple[Check, ...] = (
    *(_node_shape(label, properties) for label, properties in NODE_PROPERTIES.items()),
    *(_sublabel(base, options) for base, options in SUBLABELS.items()),
    *(_edge_shape(*relationship) for relationship in RELATIONSHIPS),
    *(_topic_shape(*topic) for topic in TOPIC_PROPERTIES.items()),
    *INVARIANTS,
)


def audit(graph: Graph, examples: int = EXAMPLES) -> list[Finding]:
    """Run every check. An empty list means the graph matches docs/schema.md."""
    findings: list[Finding] = []
    for check in CHECKS:
        result = graph.ro_query(f"{check.cypher}\nLIMIT {examples}")
        rows: list[list[object]] = result.result_set
        if rows:
            columns = [str(name) for _, name in result.header]
            findings.append(Finding(check=check, columns=columns, examples=rows))
    return findings


def format_findings(findings: Sequence[Finding], total: int) -> str:
    """The report, as lines. Empty findings still get a line saying so."""
    if not findings:
        return f"{total} checks passed: the graph matches docs/schema.md"
    lines = [f"{len(findings)} of {total} checks failed", ""]
    for finding in findings:
        lines.append(f"{finding.check.name}: {finding.check.rule}")
        lines.append(f"  {' | '.join(finding.columns)}")
        for row in finding.examples:
            lines.append(f"  {' | '.join(str(value) for value in row)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main() -> None:
    """Audit the live graph. Exits non-zero when anything fails."""
    import sys

    from bpgraph.client import connect
    from bpgraph.config import Config

    config = Config.from_env()
    db = connect(config)
    if config.live_graph not in db.list_graphs():
        sys.exit(f"{config.live_graph}: not built yet")
    findings = audit(db.select_graph(config.live_graph))
    print(format_findings(findings, len(CHECKS)))
    sys.exit(1 if findings else 0)
