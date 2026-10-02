"""GO: experimental annotations of human proteins, function only, and their
rollup through the ontology. `NOT` annotations are left out unless asked for:
GOA states what a protein is *not* involved in as an ordinary annotation."""

from typing import Annotated, Literal

from pydantic import Field

from bpgraph.api.base import Accessions, Backend, Limit, Record, Rows, page
from bpgraph.api.names import check_go_ids, check_proteins

type Namespace = Literal["biological_process", "molecular_function"]

NamespaceParam = Annotated[
    Namespace,
    Field(
        description="`biological_process`, the process axis, or "
        "`molecular_function`, the mechanistic one."
    ),
]
GoIds = Annotated[
    list[str], Field(min_length=1, description="GO ids, e.g. `GO:0097707`.")
]


class GoAnnotation(Record):
    protein_id: str
    protein_name: str
    go_id: str
    term: str
    namespace: Namespace
    qualifier: str
    evidence_code: str
    assigned_by: str
    pmid: str


def go_annotations(
    backend: Backend,
    accessions: Accessions,
    namespace: Annotated[
        Namespace | None, Field(description="Keep one namespace only.")
    ] = None,
    include_negated: Annotated[
        bool, Field(description="Also the `NOT` annotations.")
    ] = False,
    limit: Limit = 100,
) -> Rows[GoAnnotation]:
    """Human proteins' experimental GO annotations, each with its most
    specific term and the publication showing it. High-throughput codes
    (`HTP`, `HDA`, `HMP`, `HGI`, `HEP`) weigh less than a focused experiment.
    Viral proteins have none."""
    check_proteins(backend, accessions, "human")
    conditions = [
        condition
        for wanted, condition in (
            (namespace is not None, "g.namespace = $namespace"),
            (not include_negated, "NOT n.qualifier STARTS WITH 'NOT'"),
        )
        if wanted
    ]
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return page(
        backend,
        GoAnnotation,
        f"""MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
        WITH h
        MATCH (h)<-[:ANNOTATES]-(n:Annotation)
        MATCH (n)-[:OF_TERM]->(g:GoTerm)
        MATCH (n)-[:REPORTED_IN]->(b:Publication)
        WITH h, n, g, b {where}""",
        """RETURN h.id AS protein_id, h.name AS protein_name, g.go_id AS go_id,
               g.name AS term, g.namespace AS namespace,
               n.qualifier AS qualifier, n.evidence_code AS evidence_code,
               n.assigned_by AS assigned_by, b.pmid AS pmid
        ORDER BY protein_name, namespace, term, pmid""",
        "n",
        limit,
        accessions=accessions,
        namespace=namespace,
    )


class Rollup(Record):
    go_id: str
    term: str
    n_proteins: int
    proteins: list[str]
    n_background: int | None


ROLLUP = """MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
WITH h
MATCH (h)<-[:ANNOTATES]-(n:Annotation)-[:OF_TERM]->(d:GoTerm)
WITH h, n, d WHERE NOT n.qualifier STARTS WITH 'NOT'
WITH DISTINCT h, d
MATCH (d)-[:IS_A|PART_OF*0..]->(g:GoTerm)
WITH DISTINCT h, g WHERE g.namespace = $namespace
RETURN g.go_id AS go_id, g.name AS term, collect(h.name) AS proteins"""


def go_rollup(
    backend: Backend,
    accessions: Accessions,
    namespace: NamespaceParam = "biological_process",
    background: Annotated[
        list[str] | None,
        Field(
            description="Human proteins to count each term against too, e.g. "
            "the whole topic when `accessions` are its targets."
        ),
    ] = None,
    min_proteins: Annotated[
        int, Field(ge=1, description="Keep terms reaching at least this many.")
    ] = 1,
    limit: Limit = 100,
) -> Rows[Rollup]:
    """Roll a set of human proteins up the ontology: every term they or their
    annotated terms sit under, with the proteins it gathers, most first. The
    namespace root comes first, and its `n_proteins` is how many of the set
    are annotated at all. With a background, `n_background` is how many of
    it each term gathers, and the root's is how many are annotated: what an
    exact test needs. `regulation of X` is not under `X`."""
    check_proteins(backend, accessions, "human")
    if background is not None:
        check_proteins(backend, background, "human")
    counts = (
        {t.go_id: len(t.proteins) for t in _gathered(backend, background, namespace)}
        if background is not None
        else None
    )
    ranked = sorted(
        (
            Rollup(
                go_id=term.go_id,
                term=term.term,
                n_proteins=len(term.proteins),
                proteins=sorted(term.proteins),
                n_background=None if counts is None else counts.get(term.go_id, 0),
            )
            for term in _gathered(backend, accessions, namespace)
            if len(term.proteins) >= min_proteins
        ),
        key=lambda rollup: (-rollup.n_proteins, rollup.term),
    )
    return Rows(rows=ranked[:limit], total=len(ranked))


class _Gathered(Record):
    go_id: str
    term: str
    proteins: list[str]


def _gathered(
    backend: Backend, accessions: list[str], namespace: Namespace
) -> list[_Gathered]:
    return [
        _Gathered.model_validate(row)
        for row in backend.rows(ROLLUP, accessions=accessions, namespace=namespace)
    ]


class Term(Record):
    go_id: str
    name: str
    namespace: Namespace
    n_proteins: int


def search_go_terms(
    backend: Backend,
    text: Annotated[
        str, Field(min_length=1, description="Part of a term's name, any case.")
    ],
    namespace: Annotated[
        Namespace | None, Field(description="Keep one namespace only.")
    ] = None,
    limit: Limit = 100,
) -> Rows[Term]:
    """GO terms whose name contains a text, with how many human proteins are
    annotated to exactly that term. Obsolete terms are left out. A term with
    no protein of its own may still gather many below it: `go_term_proteins`."""
    keep = "AND g.namespace = $namespace" if namespace is not None else ""
    return page(
        backend,
        Term,
        f"""MATCH (g:GoTerm)
        WHERE toLower(g.name) CONTAINS toLower($text) AND NOT g.obsolete {keep}""",
        """OPTIONAL MATCH (g)<-[:OF_TERM]-(n:Annotation)-[:ANNOTATES]->(h:Human)
        WHERE NOT n.qualifier STARTS WITH 'NOT'
        RETURN g.go_id AS go_id, g.name AS name, g.namespace AS namespace,
               count(DISTINCT h) AS n_proteins
        ORDER BY n_proteins DESC, name""",
        "g",
        limit,
        text=text,
        namespace=namespace,
    )


class TermProtein(Record):
    protein_id: str
    protein_name: str
    go_id: str
    term: str
    evidence_code: str
    pmid: str


def go_term_proteins(
    backend: Backend,
    go_ids: GoIds,
    descendants: Annotated[
        bool, Field(description="Also the proteins annotated to terms below.")
    ] = True,
    limit: Limit = 100,
) -> Rows[TermProtein]:
    """Human proteins annotated to GO terms, or to any term below them: a way
    to draft a topic from GO, or to find proteins a topic's list misses. One
    row per annotation: the term it is to, its evidence code and its
    publication. `NOT` annotations are left out."""
    depth = "*0.." if descendants else "*0"
    check_go_ids(backend, go_ids)
    return page(
        backend,
        TermProtein,
        f"""MATCH (g:GoTerm) WHERE g.go_id IN $go_ids
        WITH g
        MATCH (g)<-[:IS_A|PART_OF{depth}]-(d:GoTerm)
        WITH DISTINCT d
        MATCH (d)<-[:OF_TERM]-(n:Annotation)-[:ANNOTATES]->(h:Human)
        MATCH (n)-[:REPORTED_IN]->(b:Publication)
        WITH d, n, h, b WHERE NOT n.qualifier STARTS WITH 'NOT'""",
        """RETURN h.id AS protein_id, h.name AS protein_name, d.go_id AS go_id,
               d.name AS term, n.evidence_code AS evidence_code, b.pmid AS pmid
        ORDER BY protein_name, term, pmid""",
        "n",
        limit,
        go_ids=go_ids,
    )
