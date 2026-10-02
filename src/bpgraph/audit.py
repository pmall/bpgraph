"""Auditing a built graph against docs/schema.md.

The constraint gate in `schema.py` only proves that natural keys are unique.
Everything else the schema promises — that no property is missing or
mistyped, that a `:Protein` is human or viral and never both, that a node
with no key is unique by what it links, that IntAct describes no publication
we curated, that the counters match what they count — is unchecked at build
time, because FalkorDB has no schema to check it against.

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


KNOWN_LABELS = (*NODE_PROPERTIES, "Protein", "Taxon", "Description")

NOT_KEPT = sorted(m.psimi_id for m in read_methods() if not m.keep)
"""The detection methods `curation/methods.tsv` flags `no`: no IntAct
description carries one. Our curated descriptions may."""

GROUPED = sorted([group, pmid] for pmid, group in read_groups().items())
"""`[group, pmid]` for every publication of `curation/publications.tsv`."""

PAIRS = (
    "MATCH (a:Protein)<-[r:INVOLVES]-(i:Interaction)-[s:INVOLVES]->(b:Protein)\n"
    "WHERE ID(r) < ID(s)\n"
    "WITH i, a, b\n"
)
"""Each interaction with its two proteins, once: its two edges, in id order.
A pattern may use one edge twice, so the edges are told apart."""

INVARIANTS: tuple[Check, ...] = (
    # FalkorDB 6.0.0 dropped this WHERE, and returned every interaction: an
    # engine that does is not one the graph can be queried on.
    Check(
        "engine.filters",
        "the engine keeps the WHERE of a MATCH that a following MATCH extends",
        "MATCH (i:Interaction) WHERE i.n_publications < 0\n"
        "MATCH (i)-[:INVOLVES]->(p:Protein)\n"
        "RETURN ID(i) AS interaction, i.n_publications AS n_publications",
    ),
    Check(
        "graph.labels",
        "every node carries one of the labels schema.md defines",
        "MATCH (n)\n"
        f"WHERE NOT ({' OR '.join(f'n:{label}' for label in KNOWN_LABELS)})\n"
        "RETURN ID(n) AS node, labels(n) AS labels",
    ),
    # Counted, as in `_exactly_one`: every interaction a source, and twice as
    # many edges as interactions; the partner checks below leave two each.
    Check(
        "Interaction.involves",
        "two INVOLVES edges per interaction",
        "OPTIONAL MATCH (i:Interaction)-[:INVOLVES]->()\n"
        "WITH count(DISTINCT i) AS sources\n"
        "WHERE $edges_INVOLVES <> 2 * $nodes_Interaction\n"
        "   OR sources <> $nodes_Interaction\n"
        "RETURN $nodes_Interaction AS interactions, $edges_INVOLVES AS edges, sources",
    ),
    Check(
        "VH.partners",
        "a VH interaction joins one human protein and one viral protein",
        "MATCH (i:VH)-[:INVOLVES]->(p:Protein)\n"
        "WITH i, sum(CASE WHEN p:Human THEN 1 ELSE 0 END) AS humans,\n"
        "        sum(CASE WHEN p:Viral THEN 1 ELSE 0 END) AS virals\n"
        "WHERE humans <> 1 OR virals <> 1\n"
        "RETURN ID(i) AS interaction, humans, virals",
    ),
    Check(
        "HH.partners",
        "an HH interaction joins two human proteins",
        "MATCH (i:HH)-[:INVOLVES]->(p:Protein)\n"
        "WHERE NOT p:Human\n"
        "RETURN ID(i) AS interaction, labels(p) AS partner",
    ),
    Check(
        "Interaction.unique",
        "one interaction per pair of proteins",
        PAIRS + "WITH CASE WHEN ID(a) < ID(b) THEN [ID(a), ID(b)]\n"
        "          ELSE [ID(b), ID(a)] END AS pair, count(i) AS interactions\n"
        "WHERE interactions > 1\n"
        "RETURN pair, interactions",
    ),
    _exactly_one("Description", "SUPPORTS", "one interaction behind every description"),
    _exactly_one(
        "Description", "REPORTED_IN", "one publication behind every description"
    ),
    Check(
        "Curated.stable_id",
        "a curated description has a stable id",
        "MATCH (d:Curated)\nWHERE d.stable_id = ''\nRETURN ID(d) AS description",
    ),
    Check(
        "IntAct.unique",
        "one IntAct description per interaction, publication and method",
        "MATCH (i:Interaction)<-[:SUPPORTS]-(d:IntAct)\n"
        "MATCH (d)-[:REPORTED_IN]->(b:Publication)\n"
        "WITH i, b, d.method_id AS method, count(d) AS descriptions\n"
        "WHERE descriptions > 1\n"
        "RETURN ID(i) AS interaction, b.pmid AS pmid, method, descriptions",
    ),
    # Counted: the publications of HH descriptions are ours or IntAct's, and
    # none is both when the two counts add up to all of them.
    Check(
        "IntAct.uncurated",
        "IntAct describes no publication we curated for HH interactions",
        "MATCH (d:Description)-[:SUPPORTS]->(:HH)\n"
        "MATCH (d)-[:REPORTED_IN]->(b:Publication)\n"
        "WITH count(DISTINCT b) AS publications,\n"
        "     count(DISTINCT CASE WHEN d:Curated THEN b END) AS ours,\n"
        "     count(DISTINCT CASE WHEN d:IntAct THEN b END) AS intact\n"
        "WHERE ours + intact <> publications\n"
        "RETURN publications, ours, intact",
    ),
    Check(
        "VH.curated",
        "every VH description is curated",
        "MATCH (d:IntAct)-[:SUPPORTS]->(:VH)\nRETURN ID(d) AS description",
    ),
    _exactly_one("Annotation", "ANNOTATES", "one protein behind every annotation"),
    _exactly_one("Annotation", "OF_TERM", "one term behind every annotation"),
    Check(
        "Annotation.published",
        "a publication behind every annotation",
        "OPTIONAL MATCH (a:Annotation)-[:REPORTED_IN]->()\n"
        "WITH count(DISTINCT a) AS published\n"
        "WHERE published <> $nodes_Annotation\n"
        "RETURN $nodes_Annotation AS annotations, published",
    ),
    Check(
        "Annotation.unique",
        "one annotation per protein, term and qualifier",
        "MATCH (p:Human)<-[:ANNOTATES]-(a:Annotation)-[:OF_TERM]->(g:GoTerm)\n"
        "WITH p, g, a.qualifier AS qualifier, count(a) AS annotations\n"
        "WHERE annotations > 1\n"
        "RETURN p.accession AS accession, g.go_id AS go_id, qualifier, annotations",
    ),
    _edge_properties("REPORTED_IN", "Description", ()),
    _edge_properties("REPORTED_IN", "Annotation", ("evidence_codes",)),
    Check(
        "Annotation.evidence",
        "an annotation's publications show it by experimental evidence",
        "MATCH (a:Annotation)-[r:REPORTED_IN]->(b:Publication)\n"
        "WHERE size(r.evidence_codes) = 0\n"
        f"   OR any(c IN r.evidence_codes WHERE NOT c IN {list(EXPERIMENTAL)})\n"
        "RETURN ID(a) AS annotation, b.pmid AS pmid, r.evidence_codes AS codes",
    ),
    Check(
        "Annotation.functional",
        "no annotation is to a cellular component, or at or below protein binding",
        "MATCH (a:Annotation)-[:OF_TERM]->(g:GoTerm)\n"
        f"WHERE NOT g.namespace IN {list(GO_NAMESPACES)}\n"
        "   OR (g)-[:IS_A|PART_OF*0..]->(:GoTerm {go_id: "
        f"'{PROTEIN_BINDING}'}})\n"
        "RETURN ID(a) AS annotation, g.go_id AS go_id, g.name AS name",
    ),
    Check(
        "IntAct.method_kept",
        "an IntAct description carries a method curation/methods.tsv keeps",
        "MATCH (d:IntAct)\n"
        f"WHERE d.method_id IN {NOT_KEPT}\n"
        "RETURN ID(d) AS description, d.method_id AS method_id",
    ),
    Check(
        "IntAct.unrepeated",
        "no interaction has IntAct descriptions from two publications of one "
        "group of curation/publications.tsv",
        f"UNWIND {GROUPED} AS grouped\n"
        "MATCH (b:Publication {pmid: grouped[1]})<-[:REPORTED_IN]-(d:IntAct)\n"
        "      -[:SUPPORTS]->(i:Interaction)\n"
        "WITH grouped[0] AS group, i, collect(DISTINCT b.pmid) AS pmids\n"
        "WHERE size(pmids) > 1\n"
        "RETURN group, ID(i) AS interaction, pmids",
    ),
    Check(
        "Description.method",
        "a method id is a PSI-MI id, and its name is never empty",
        "MATCH (d:Description)\n"
        "WHERE NOT d.method_id STARTS WITH 'MI:' OR size(d.method_id) <> 7\n"
        "   OR d.method_name = ''\n"
        "RETURN ID(d) AS description, d.method_id AS method_id",
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
        "RETURN ID(i) AS interaction, descriptions, publications, methods, peptides",
    ),
    # Counted: as many shortcuts as interactions, and one copying each
    # interaction's counters between its two proteins.
    Check(
        "INTERACTS_WITH.count",
        "one shortcut edge per interaction",
        "WITH 1 AS one\n"
        "WHERE $edges_INTERACTS_WITH <> $nodes_Interaction\n"
        "RETURN $nodes_Interaction AS interactions, $edges_INTERACTS_WITH AS edges",
    ),
    Check(
        "INTERACTS_WITH.shortcut",
        "every interaction has a shortcut edge between its two proteins, "
        "copying its counters",
        PAIRS + "MATCH (a)-[e:INTERACTS_WITH]-(b)\n"
        "WHERE e.n_descriptions = i.n_descriptions\n"
        "  AND e.n_publications = i.n_publications\n"
        "  AND e.n_methods = i.n_methods AND e.n_peptides = i.n_peptides\n"
        "WITH count(DISTINCT i) AS copied\n"
        "WHERE copied <> $nodes_Interaction\n"
        "RETURN $nodes_Interaction AS interactions, copied",
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
        "a viral protein has one IN_TAXON edge, to the virus of its taxon id",
        "MATCH (p:Viral)\n"
        "OPTIONAL MATCH (p)-[:IN_TAXON]->(v:Virus)\n"
        "WITH p, collect(v.ncbi_taxon_id) AS taxa\n"
        "WHERE taxa <> [p.ncbi_taxon_id]\n"
        "RETURN p.ncbi_taxon_id AS ncbi_taxon_id, p.name AS name, taxa",
    ),
    Check(
        "Human.taxon",
        "a human protein gets no Taxon node",
        "MATCH (p:Human)-[:IN_TAXON]->()\nRETURN p.accession AS accession",
    ),
    Check(
        "Taxon.parent",
        "a virus has at most one family",
        "MATCH (t:Virus)\n"
        "WHERE outdegree(t, 'PARENT') > 1\n"
        "RETURN t.ncbi_taxon_id AS ncbi_taxon_id, outdegree(t, 'PARENT') AS parents",
    ),
    Check(
        "Taxon.used",
        "every virus has a protein, and every family a virus",
        "MATCH (t:Taxon)\n"
        "WHERE (t:Virus AND NOT (t)<-[:IN_TAXON]-(:Viral))\n"
        "   OR (t:Family AND NOT (t)<-[:PARENT]-(:Virus))\n"
        "RETURN t.ncbi_taxon_id AS ncbi_taxon_id, t.name AS name",
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
        "Peptide.described",
        "every peptide is reported by a curated description, cut from a "
        "protein and binding one",
        "MATCH (x:Peptide)\n"
        "WHERE NOT (x)<-[:REPORTS]-(:Curated) OR NOT (x)-[:FROM]->(:Protein)\n"
        "   OR NOT (x)-[:BINDS]->(:Protein)\n"
        "RETURN x.sequence AS sequence",
    ),
    Check(
        "REPORTS.source",
        "of a reporting description's two proteins, exactly one is a source of "
        "the peptide, and one it binds",
        "MATCH (x:Peptide)<-[:REPORTS]-(d:Curated)-[:SUPPORTS]->(i:Interaction)\n"
        "MATCH (i)-[:INVOLVES]->(p:Protein)\n"
        "OPTIONAL MATCH (x)-[f:FROM]->(p)\n"
        "OPTIONAL MATCH (x)-[t:BINDS]->(p)\n"
        "WITH x, d, count(DISTINCT CASE WHEN f IS NULL THEN NULL ELSE p END)\n"
        "             AS sources,\n"
        "           count(DISTINCT CASE WHEN t IS NULL THEN NULL ELSE p END)\n"
        "             AS targets\n"
        "WHERE sources <> 1 OR targets = 0\n"
        "RETURN x.sequence AS sequence, d.stable_id AS stable_id",
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
