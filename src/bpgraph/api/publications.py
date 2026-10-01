"""Publications: their text, what each one showed, and full-text search."""

from typing import Annotated

from pydantic import Field

from bpgraph.api.base import Backend, Limit, Record, Rows, paged, whole
from bpgraph.api.names import check_pmids

Pmids = Annotated[list[str], Field(min_length=1, description="PubMed ids.")]


class Publication(Record):
    pmid: str
    title: str
    abstract: str | None
    journal: str
    year: int
    authors: list[str]


def publications(
    backend: Backend,
    pmids: Pmids,
    abstracts: Annotated[
        bool, Field(description="Also the abstracts, which are long.")
    ] = False,
) -> Rows[Publication]:
    """Publications' title, journal, year, authors and, if asked, abstract.
    The abstract is where a paper says what an interaction does: ask for it
    once the papers that matter are known.
    A pmid PubMed did not return has empty text and year 0."""
    check_pmids(backend, pmids)
    return whole(
        [
            Publication.model_validate(row)
            for row in backend.rows(
                """MATCH (b:Publication) WHERE b.pmid IN $pmids
            RETURN b.pmid AS pmid, b.title AS title,
                   CASE WHEN $abstracts THEN b.abstract END AS abstract,
                   b.journal AS journal, b.year AS year, b.authors AS authors""",
                pmids=pmids,
                abstracts=abstracts,
            )
        ]
    )


class Described(Record):
    interaction_id: str
    a_name: str
    b_name: str
    method_name: str


class Shown(Record):
    protein_id: str
    protein_name: str
    go_id: str
    term: str
    qualifier: str
    evidence_code: str


class Cited(Record):
    protein_id: str
    protein_name: str


class PublicationContent(Record):
    pmid: str
    title: str
    n_descriptions: int
    descriptions: list[Described]
    n_annotations: int
    annotations: list[Shown]
    n_function_cites: int
    function_cites: list[Cited]


def publication_content(
    backend: Backend,
    pmid: Annotated[str, Field(description="A PubMed id.")],
    limit: Limit = 100,
) -> PublicationContent:
    """Everything one publication backs in the graph: the interactions it
    described, the GO annotations it showed and the proteins whose UniProt
    function text cites it. Each list is cut at `limit`, beside its full
    count: a screen such as BioPlex describes tens of thousands of pairs."""
    check_pmids(backend, [pmid])
    head = backend.rows(
        """MATCH (b:Publication {pmid: $pmid})
        RETURN b.pmid AS pmid, b.title AS title""",
        pmid=pmid,
    )
    counts = backend.rows(
        """MATCH (b:Publication {pmid: $pmid})
        OPTIONAL MATCH (b)<-[:REPORTED_IN]-(d:Description)
        WITH b, count(d) AS n_descriptions
        OPTIONAL MATCH (b)<-[:REPORTED_IN]-(n:Annotation)
        WITH b, n_descriptions, count(n) AS n_annotations
        OPTIONAL MATCH (b)<-[:FUNCTION_CITES]-(p:Protein)
        RETURN n_descriptions, n_annotations, count(p) AS n_function_cites""",
        pmid=pmid,
    )[0]
    described = backend.rows(
        """MATCH (b:Publication {pmid: $pmid})<-[:REPORTED_IN]-(d:Description)
        MATCH (d)-[:SUPPORTS]->(i:Interaction)
        MATCH (i)-[:INVOLVES {side: 'a'}]->(a:Protein)
        MATCH (i)-[:INVOLVES {side: 'b'}]->(c:Protein)
        RETURN i.id AS interaction_id, a.name AS a_name, c.name AS b_name,
               d.method_name AS method_name
        ORDER BY interaction_id
        LIMIT $limit""",
        pmid=pmid,
        limit=limit,
    )
    shown = backend.rows(
        """MATCH (b:Publication {pmid: $pmid})<-[:REPORTED_IN]-(n:Annotation)
        MATCH (n)-[:ANNOTATES]->(h:Human)
        MATCH (n)-[:OF_TERM]->(g:GoTerm)
        RETURN h.id AS protein_id, h.name AS protein_name, g.go_id AS go_id,
               g.name AS term, n.qualifier AS qualifier,
               n.evidence_code AS evidence_code
        ORDER BY protein_name, term
        LIMIT $limit""",
        pmid=pmid,
        limit=limit,
    )
    cited = backend.rows(
        """MATCH (b:Publication {pmid: $pmid})<-[:FUNCTION_CITES]-(p:Protein)
        RETURN p.id AS protein_id, p.name AS protein_name
        ORDER BY protein_name
        LIMIT $limit""",
        pmid=pmid,
        limit=limit,
    )
    return PublicationContent.model_validate(
        {
            **head[0],
            **counts,
            "descriptions": described,
            "annotations": shown,
            "function_cites": cited,
        }
    )


class Hit(Record):
    pmid: str
    title: str
    journal: str
    year: int
    score: float


def search_publications(
    backend: Backend,
    text: Annotated[
        str,
        Field(
            min_length=1,
            description="RediSearch syntax over title and abstract: words are "
            'ANDed, `a|b` is OR, `-a` excludes, `"a b"` is a phrase, `ferropt*` '
            "a prefix.",
        ),
    ],
    limit: Limit = 100,
) -> Rows[Hit]:
    """Full-text search over the titles and abstracts of every publication in
    the graph, best match first. Every publication here backs an interaction,
    a GO annotation or a function text: `publication_content` says which."""
    found = paged(
        backend,
        """CALL db.idx.fulltext.queryNodes('Publication', $text) YIELD node, score""",
        """RETURN node.pmid AS pmid, node.title AS title, node.journal AS journal,
               node.year AS year, score
        ORDER BY score DESC, year DESC""",
        "node",
        limit,
        text=text,
    )
    return Rows(rows=[Hit.model_validate(r) for r in found.rows], total=found.total)
