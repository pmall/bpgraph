"""Auditing a built graph against docs/schema.md.

The constraint gate in `schema.py` only proves that keys are unique. Everything
else the schema promises — that no property is missing or mistyped, that a
`:Protein` is human or viral and never both, that a derived id agrees with the
values it was derived from, that `:VH` puts the human on side `a`, that the
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

NODE_PROPERTIES: Mapping[str, Mapping[str, str]] = {
    "Protein": {
        "id": "String",
        "accession": "String",
        "start": "Integer",
        "stop": "Integer",
        "name": "String",
        "description": "String",
        "function": "String",
        "taxon_id": "Integer",
        "taxon_name": "String",
    },
    "Taxon": {"taxon_id": "Integer", "name": "String", "rank": "String"},
    "ProteinSet": {"name": "String"},
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
"""

SUBLABELS: Mapping[str, tuple[str, str]] = {
    "Protein": ("Human", "Viral"),
    "Interaction": ("HH", "VH"),
}
"""Labels that carry a type: exactly one of the pair, beside the base label."""

RELATIONSHIPS: tuple[tuple[str, str, str, tuple[str, ...] | None], ...] = (
    ("INVOLVES", "Interaction", "Protein", ("side",)),
    ("SUPPORTS", "Description", "Interaction", ()),
    ("REPORTED_IN", "Description", "Publication", ()),
    ("DETECTED_BY", "Description", "Method", ()),
    ("REPORTS", "Description", "Peptide", ("source_side",)),
    ("IN_TAXON", "Viral", "Taxon", ()),
    ("PARENT", "Taxon", "Taxon", ()),
    ("MEMBER_OF", "Protein", "ProteinSet", None),
    (
        "ANNOTATED_WITH",
        "Protein",
        "GoTerm",
        ("evidence_code", "assigned_by", "qualifier"),
    ),
    ("IS_A", "GoTerm", "GoTerm", ()),
    ("PART_OF", "GoTerm", "GoTerm", ()),
)
"""Type, the labels it must join, and its properties. `None` means free-form."""


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


KNOWN_LABELS = tuple(NODE_PROPERTIES)

INVARIANTS: tuple[Check, ...] = (
    Check(
        "graph.labels",
        "every node carries one of the labels schema.md defines",
        "MATCH (n)\n"
        f"WHERE NOT ({' OR '.join(f'n:{label}' for label in KNOWN_LABELS)})\n"
        "RETURN ID(n) AS node, labels(n) AS labels",
    ),
    Check(
        "Protein.id",
        "a human id is its bare accession, a viral one carries its span",
        "MATCH (p:Protein)\n"
        "WITH p, CASE WHEN p:Human THEN p.accession\n"
        "            ELSE p.accession + ':' + toString(p.start)\n"
        "                 + '-' + toString(p.stop)\n"
        "       END AS derived\n"
        "WHERE p.id <> derived\n"
        "RETURN p.id AS id, derived",
    ),
    Check(
        "Protein.coordinates",
        "1 <= start <= stop, and a human protein is the full chain",
        "MATCH (p:Protein)\n"
        "WHERE p.start < 1 OR p.stop < p.start OR (p:Human AND p.start <> 1)\n"
        "RETURN p.id AS id, p.start AS start, p.stop AS stop",
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
        "REPORTS.source_side",
        "a reported peptide names a slot of its description's interaction",
        "MATCH (d:Description)-[r:REPORTS]->(:Peptide)\n"
        "WHERE NOT r.source_side IN ['a', 'b']\n"
        "RETURN d.id AS id, r.source_side AS source_side",
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
        "a viral protein has one IN_TAXON edge, to the taxon it names",
        "MATCH (p:Viral)\n"
        "WITH p, [(p)-[:IN_TAXON]->(t) | t.taxon_id] AS taxa\n"
        "WHERE size(taxa) <> 1 OR taxa[0] <> p.taxon_id\n"
        "RETURN p.id AS id, p.taxon_id AS taxon_id, taxa",
    ),
    Check(
        "Human.taxon",
        "a human protein is taxon 9606 and gets no Taxon node",
        "MATCH (p:Human)\n"
        "WHERE p.taxon_id <> 9606 OR (p)-[:IN_TAXON]->()\n"
        "RETURN p.id AS id, p.taxon_id AS taxon_id",
    ),
    Check(
        "Taxon.parent",
        "a taxon has at most one parent, and is not its own",
        "MATCH (t:Taxon)\n"
        "WITH t, [(t)-[:PARENT]->(p) | p.taxon_id] AS parents\n"
        "WHERE size(parents) > 1 OR t.taxon_id IN parents\n"
        "RETURN t.taxon_id AS taxon_id, parents",
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
