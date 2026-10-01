"""Auditing a built graph against docs/schema.md.

The constraint gate in `schema.py` only proves that keys are unique. Everything
else the schema promises — that no property is missing or mistyped, that a
`:Protein` is human or viral and never both, that a derived id agrees with the
values it was derived from, that a description comes from IntAct or from
exactly one curated row, that `:VH` puts the human on side `a`, that the
counters match what they count — is unchecked at build time, because FalkorDB
has no schema to check it against.

**The expectations are restated from docs/schema.md by hand, here and in
`shape.py`, and that is the point.** Deriving them from the loaders or the
writers would only prove the code agrees with itself; written out separately,
they disagree when either side drifts, and that disagreement is the finding.

The curated lists are read, not restated: `curation/methods.tsv` says which
methods IntAct's descriptions may carry, and `curation/publications.tsv` which
publications repeat one experiment. They are the rules, not code.

Every check is one read-only query that returns the rows *breaking* its rule,
so an empty result is a pass. Queries end in `RETURN` — the runner appends the
limit. The audit must stay quick enough to run after every build, well
under a minute, and it runs its checks side by side to get there. Across a
large label, count rather than test node by node: compare the edges, the
distinct sources and the nodes, with the totals the runner passes as
parameters. Never use `outdegree` on a type with many edges, never a pattern
comprehension, and never walk a variable-length path down the GO DAG, whose
paths explode.
"""

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from falkordb.graph import Graph

from bpgraph.methods import read_methods
from bpgraph.publications import read_groups
from bpgraph.shape import NODE_PROPERTIES, RELATIONSHIPS, SUBLABELS

EXAMPLES = 5

GO_ROOTS = ("GO:0008150", "GO:0003674")
"""The two namespace roots loaded: biological process and molecular function.
Nothing sits above them, so they are the one place the ancestor closure is
allowed to stop."""

GO_NAMESPACES = ("biological_process", "molecular_function")
"""What GO says about a protein's function; `cellular_component` is left out."""

PROTEIN_BINDING = "GO:0005515"
"""No annotation may sit at or below it: those are interactions, restated."""

EXPERIMENTAL = (
    "EXP",
    "IDA",
    "IPI",
    "IMP",
    "IGI",
    "IEP",
    "HTP",
    "HDA",
    "HMP",
    "HGI",
    "HEP",
)
"""The GO evidence codes an annotation may carry: experimental ones only."""


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


def _edge_joins(kind: str, source: str, target: str) -> Check:
    """Every edge of a type joins the labels it may: the edges between those
    labels are all the edges of the type, `$edges_<type>`. Counted rather than
    scanned, since an edge from anywhere means visiting every node."""
    joined = "\n".join(
        f"OPTIONAL MATCH (:{label})-[r:{kind}]->(:{target})\n"
        f"WITH {'joined + ' if i else ''}count(r) AS joined"
        for i, label in enumerate(source.split("|"))
    )
    return Check(
        name=f"{kind}.joins",
        rule=f"every {kind} edge is (:{source})-[:{kind}]->(:{target})",
        cypher=(
            f"{joined}\n"
            f"WITH joined WHERE joined <> $edges_{kind}\n"
            f"RETURN $edges_{kind} AS edges, joined"
        ),
    )


def _edge_properties(kind: str, source: str, properties: tuple[str, ...]) -> Check:
    """The properties an edge carries, entered from its source's label: an
    edge from elsewhere is `_edge_joins`'s finding."""
    tests = [f"typeOf(r.{name}) = 'Null'" for name in properties]
    tests.append(f"size(keys(r)) <> {len(properties)}")
    return Check(
        name=f"{kind}.properties",
        rule=f"{kind} carries {', '.join(properties) or 'no properties'}",
        cypher=(
            f"MATCH (:{source.split('|')[0]})-[r:{kind}]->()\n"
            f"WHERE {' OR '.join(tests)}\n"
            "RETURN ID(r) AS edge, keys(r) AS keys"
        ),
    )


def _edge_shape(
    kind: str, source: str, target: str, properties: tuple[str, ...] | None
) -> tuple[Check, ...]:
    """The labels an edge joins, and the properties it carries."""
    joins = _edge_joins(kind, source, target)
    if properties is None:
        return (joins,)
    return joins, *(
        _edge_properties(kind, label, properties) for label in source.split("|")
    )


def _exactly_one(label: str, kind: str, rule: str) -> Check:
    """Every node of a label has exactly one outgoing edge of a type. Counted:
    when the distinct sources are all the nodes, each has one edge at least,
    and when the edges are as many as the nodes, each has one at most.
    `outdegree` would say it per node, but on 4.22 its cost grows with the
    type's edges across the whole graph: a million descriptions never end."""
    return Check(
        name=f"{label}.{kind}",
        rule=rule,
        cypher=(
            f"OPTIONAL MATCH (:{label})-[r:{kind}]->() WITH count(r) AS edges\n"
            f"OPTIONAL MATCH (n:{label})-[:{kind}]->()\n"
            "WITH edges, count(DISTINCT n) AS sources\n"
            f"WHERE edges <> $nodes_{label} OR sources <> $nodes_{label}\n"
            f"RETURN $nodes_{label} AS nodes, edges, sources"
        ),
    )


KNOWN_LABELS = (*NODE_PROPERTIES, "Taxon")

NOT_KEPT = sorted(m.psimi_id for m in read_methods() if not m.keep)
"""The detection methods `curation/methods.tsv` flags `no`: no IntAct
description carries one. Our curated descriptions may."""

GROUPED = sorted([group, pmid] for pmid, group in read_groups().items())
"""`[group, pmid]` for every publication of `curation/publications.tsv`."""

INVARIANTS: tuple[Check, ...] = (
    # FalkorDB 6.0.0 dropped this WHERE, and returned every interaction: an
    # engine that does is not one the graph can be queried on.
    Check(
        "engine.filters",
        "the engine keeps the WHERE of a MATCH that a following MATCH extends",
        "MATCH (i:Interaction) WHERE i.n_publications < 0\n"
        "MATCH (i)-[:INVOLVES]->(p:Protein)\n"
        "RETURN i.id AS id, i.n_publications AS n_publications",
    ),
    Check(
        "graph.labels",
        "every node carries one of the labels schema.md defines",
        "MATCH (n)\n"
        f"WHERE NOT ({' OR '.join(f'n:{label}' for label in KNOWN_LABELS)})\n"
        "RETURN ID(n) AS node, labels(n) AS labels",
    ),
    Check(
        "Viral.id",
        "a viral id is its curated virus's taxon id and its name",
        "MATCH (p:Viral)-[:IN_TAXON]->(v:Virus)\n"
        "WHERE p.id <> toString(v.taxon_id) + ':' + p.name\n"
        "RETURN p.id AS id, v.taxon_id AS virus, p.name AS name",
    ),
    # Counted, as in `_exactly_one`: each side reaching every interaction, and
    # twice as many edges as interactions, leaves one edge per side.
    Check(
        "Interaction.slots",
        "two INVOLVES edges, one side 'a' and one side 'b'",
        "OPTIONAL MATCH (i:Interaction)-[:INVOLVES {side: 'a'}]->()\n"
        "WITH count(DISTINCT i) AS with_a\n"
        "OPTIONAL MATCH (i:Interaction)-[:INVOLVES {side: 'b'}]->()\n"
        "WITH with_a, count(DISTINCT i) AS with_b\n"
        "WHERE $edges_INVOLVES <> 2 * $nodes_Interaction\n"
        "   OR with_a <> $nodes_Interaction OR with_b <> $nodes_Interaction\n"
        "RETURN $nodes_Interaction AS interactions, $edges_INVOLVES AS edges,\n"
        "       with_a, with_b",
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
    _exactly_one("Description", "SUPPORTS", "one interaction behind every description"),
    _exactly_one(
        "Description", "REPORTED_IN", "one publication behind every description"
    ),
    Check(
        "Description.source",
        "a description is IntAct's, keyed by its IntAct id and pair, or one "
        "curated row's, keyed by its stable_id; VH descriptions are curated",
        "MATCH (d:Description)-[:SUPPORTS]->(i:Interaction)\n"
        "WHERE (d.intact_id = ''\n"
        "       AND (size(d.stable_ids) <> 1 OR d.id <> d.stable_ids[0]))\n"
        "   OR (d.intact_id <> '' AND d.id <> d.intact_id + '|' + i.id)\n"
        "   OR (i:VH AND d.intact_id <> '')\n"
        "RETURN d.id AS id, d.intact_id AS intact_id, d.stable_ids AS stable_ids",
    ),
    _exactly_one("Annotation", "ANNOTATES", "one protein behind every annotation"),
    _exactly_one("Annotation", "OF_TERM", "one term behind every annotation"),
    _exactly_one(
        "Annotation", "REPORTED_IN", "one publication behind every annotation"
    ),
    Check(
        "Annotation.evidence",
        "an annotation stands on experimental evidence",
        "MATCH (a:Annotation)\n"
        f"WHERE NOT a.evidence_code IN {list(EXPERIMENTAL)}\n"
        "RETURN a.id AS id, a.evidence_code AS code",
    ),
    Check(
        "Annotation.functional",
        "no annotation is to a cellular component, or at or below protein binding",
        "MATCH (a:Annotation)-[:OF_TERM]->(g:GoTerm)\n"
        f"WHERE NOT g.namespace IN {list(GO_NAMESPACES)}\n"
        "   OR (g)-[:IS_A|PART_OF*0..]->(:GoTerm {go_id: "
        f"'{PROTEIN_BINDING}'}})\n"
        "RETURN a.id AS id, g.go_id AS go_id, g.name AS name",
    ),
    Check(
        "Annotation.id",
        "the id joins protein, term, pmid, evidence, assigner and qualifier",
        "MATCH (p:Protein)<-[:ANNOTATES]-(a:Annotation)-[:OF_TERM]->(g:GoTerm)\n"
        "MATCH (a)-[:REPORTED_IN]->(b:Publication)\n"
        "WITH a, p.id + '|' + g.go_id + '|' + b.pmid + '|' + a.evidence_code + '|'\n"
        "        + a.assigned_by + '|' + a.qualifier AS derived\n"
        "WHERE a.id <> derived\n"
        "RETURN a.id AS id, derived",
    ),
    Check(
        "REPORTS.source_side",
        "a reported peptide names a slot of its description's interaction",
        "MATCH (d:Description)-[r:REPORTS]->(:Peptide)\n"
        "WHERE NOT r.source_side IN ['a', 'b']\n"
        "RETURN d.id AS id, r.source_side AS source_side",
    ),
    Check(
        "Description.method_kept",
        "an IntAct description carries a method curation/methods.tsv keeps",
        "MATCH (d:Description)\n"
        f"WHERE d.intact_id <> '' AND d.method_id IN {NOT_KEPT}\n"
        "RETURN d.id AS id, d.method_id AS method_id, d.method_name AS method_name",
    ),
    Check(
        "Description.unrepeated",
        "no interaction has IntAct descriptions from two publications of one "
        "group of curation/publications.tsv",
        f"UNWIND {GROUPED} AS grouped\n"
        "MATCH (b:Publication {pmid: grouped[1]})<-[:REPORTED_IN]-(d:Description)\n"
        "      -[:SUPPORTS]->(i:Interaction)\n"
        "WHERE d.intact_id <> ''\n"
        "WITH grouped[0] AS group, i, collect(DISTINCT b.pmid) AS pmids\n"
        "WHERE size(pmids) > 1\n"
        "RETURN group, i.id AS id, pmids",
    ),
    Check(
        "Description.method",
        "a method id is a PSI-MI id, and its name is never empty",
        "MATCH (d:Description)\n"
        "WHERE NOT d.method_id STARTS WITH 'MI:' OR size(d.method_id) <> 7\n"
        "   OR d.method_name = ''\n"
        "RETURN d.id AS id, d.method_id AS method_id, d.method_name AS method_name",
    ),
    Check(
        "Interaction.counters",
        "the counters equal what they count",
        "MATCH (i:Interaction)<-[:SUPPORTS]-(d:Description)\n"
        "OPTIONAL MATCH (d)-[:REPORTED_IN]->(b:Publication)\n"
        "OPTIONAL MATCH (d)-[:REPORTS]->(x:Peptide)\n"
        "WITH i, count(DISTINCT d) AS descriptions,\n"
        "        count(DISTINCT b) AS publications,\n"
        "        count(DISTINCT d.method_id) AS methods,\n"
        "        count(DISTINCT x) AS peptides\n"
        "WHERE i.n_descriptions <> descriptions OR i.n_publications <> publications\n"
        "   OR i.n_methods <> methods OR i.n_peptides <> peptides\n"
        "RETURN i.id AS id, descriptions, publications, methods, peptides",
    ),
    Check(
        "INTERACTS_WITH.shortcut",
        "every interaction has one shortcut edge, from side 'a' to side 'b', "
        "copying its counters",
        "MATCH (i:Interaction)-[:INVOLVES {side: 'a'}]->(a:Protein)\n"
        "MATCH (i)-[:INVOLVES {side: 'b'}]->(b:Protein)\n"
        "WITH i, [(a)-[r:INTERACTS_WITH {interaction_id: i.id}]->(b) | r] AS edges\n"
        "WHERE size(edges) <> 1\n"
        "   OR edges[0].n_descriptions <> i.n_descriptions\n"
        "   OR edges[0].n_publications <> i.n_publications\n"
        "   OR edges[0].n_methods <> i.n_methods\n"
        "   OR edges[0].n_peptides <> i.n_peptides\n"
        "RETURN i.id AS id, size(edges) AS edges",
    ),
    Check(
        "Interaction.supported",
        "no interaction without a description behind it",
        "OPTIONAL MATCH (:Description)-[:SUPPORTS]->(i:Interaction)\n"
        "WITH count(DISTINCT i) AS supported\n"
        "WHERE supported <> $nodes_Interaction\n"
        "RETURN $nodes_Interaction AS interactions, supported",
    ),
    Check(
        "Viral.taxon",
        "a viral protein has one IN_TAXON edge",
        "MATCH (p:Viral)\n"
        "WHERE outdegree(p, 'IN_TAXON') <> 1\n"
        "RETURN p.id AS id, outdegree(p, 'IN_TAXON') AS taxa",
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
        "WHERE outdegree(t, 'PARENT') > 1\n"
        "RETURN t.taxon_id AS taxon_id, outdegree(t, 'PARENT') AS parents",
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
        "GoTerm.namespace",
        "every term is a biological process or a molecular function",
        "MATCH (t:GoTerm)\n"
        f"WHERE NOT t.namespace IN {list(GO_NAMESPACES)}\n"
        "RETURN t.go_id AS go_id, t.namespace AS namespace",
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
    # One step at a time: a term that is not annotated but has a child leads,
    # down acyclic edges, to one that is.
    Check(
        "GoTerm.reached",
        "every term is annotated, or lies above one that is",
        "MATCH (t:GoTerm)\n"
        "WHERE NOT (t)<-[:OF_TERM]-(:Annotation)\n"
        "  AND NOT (t)<-[:IS_A|PART_OF]-(:GoTerm)\n"
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
        "every publication backs a description, an annotation or a function text",
        "MATCH (b:Publication)\n"
        "WHERE NOT (b)<-[:REPORTED_IN]-() AND NOT (b)<-[:FUNCTION_CITES]-()\n"
        "RETURN b.pmid AS pmid",
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
    *(check for r in RELATIONSHIPS for check in _edge_shape(*r)),
    *INVARIANTS,
)


COUNTED = ("Interaction", "Description", "Annotation")
"""The labels whose node count a check compares against, as `$nodes_<label>`."""


def totals(graph: Graph) -> dict[str, object]:
    """`$edges_<type>` for every relationship and `$nodes_<label>` for the
    labels counted. Each is a bare `RETURN count(x)`, which FalkorDB answers
    from its own tally: the same count behind a `WITH` scans every node. The
    edge must be bound and counted: 4.22 counts the rows of `()-[:T]->()` one
    per pair of nodes, so a homodimer's two INVOLVES edges would count once."""

    def count(pattern: str) -> int:
        return int(graph.ro_query(f"MATCH {pattern} RETURN count(x)").result_set[0][0])

    return {
        **{f"edges_{kind}": count(f"()-[x:{kind}]->()") for kind, *_ in RELATIONSHIPS},
        **{f"nodes_{label}": count(f"(x:{label})") for label in COUNTED},
    }


def audit(graph: Graph, examples: int = EXAMPLES, workers: int = 4) -> list[Finding]:
    """Run every check, `workers` at a time: they only read, and the server
    runs reads side by side on its threads. An empty list means the graph
    matches docs/schema.md."""
    params = totals(graph)

    def run(check: Check) -> Finding | None:
        result = graph.ro_query(f"{check.cypher}\nLIMIT {examples}", params)
        rows: list[list[object]] = result.result_set
        if not rows:
            return None
        columns = [str(name) for _, name in result.header]
        return Finding(check=check, columns=columns, examples=rows)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [finding for finding in pool.map(run, CHECKS) if finding is not None]


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
    import os
    import sys

    from bpgraph.client import connect
    from bpgraph.config import Config

    config = Config.from_env()
    db = connect(config)
    # Not GRAPH.LIST: it once missed a graph swapped in over one 6.0 wrote.
    if not db.connection.exists(config.live_graph):
        sys.exit(f"{config.live_graph}: not built yet")
    findings = audit(
        db.select_graph(config.live_graph),
        workers=int(os.environ.get("FALKORDB_THREADS", "4")),
    )
    print(format_findings(findings, len(CHECKS)))
    sys.exit(1 if findings else 0)
