"""The Gene Ontology, cut to what an export's human proteins are annotated with.

The relational database holds no GO at all, so it is built here from two public
dumps and written into the run directory beside the function text —
`data/2026-09-09/go_terms.tsv` and its two companions, beside `export/` rather
than in it because the files are this repo's and not the relational
database's. The loader reads them back from there; this module never touches
the graph, and those files are the only thing between the two.

**Human proteins only.** GOA does annotate viral proteins — there is a whole
branch of terms about what a virus does to its host — but it annotates a whole
accession, while a viral protein here is one mature chain excised from a
polyprotein and nothing in GOA says which chain a term belongs to. The
function text gets away with it because UniProt scopes a FUNCTION comment to a
chain by naming its molecule; there is no equivalent here, so attributing a
term to NS5A rather than to the polyprotein around it would be a guess.

Two dumps, fetched into the run directory the way the taxonomy is, so a run
reads releases at least as recent as its export:

- **`go-basic.obo`** is the ontology. It is the release filtered to the
  relations annotations propagate over and guaranteed acyclic, which is exactly
  the traversal the schema promises. Of the relations it keeps, only `is_a` and
  `part_of` are modelled: the three `regulates` relations propagate nothing,
  since a protein involved in `regulation of X` is not involved in `X`.
- **`goa_human.gaf.gz`** is every GO annotation on the human reference
  proteome, with the evidence code, the qualifier and the assigning database
  the export format asks for. One snapshot rather than a paged request per
  protein, and everything outside the export is dropped on the way past.

An annotation is made to the most specific term that fits, so the file carries
the **full ancestor closure** above every annotated term as well. Without it,
rolling an annotation up to a coarse process would stop at whatever terms
happened to be annotated directly.
"""

import gzip
import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from shutil import copyfileobj
from urllib.request import Request, urlopen

from bpgraph.enums import GoNamespace, GoRelation, ProteinKind
from bpgraph.models import GoEdge, GoTerm
from bpgraph.run import Run

logger = logging.getLogger(__name__)

ONTOLOGY_URL = "https://purl.obolibrary.org/obo/go/go-basic.obo"
ANNOTATIONS_URL = "https://ftp.ebi.ac.uk/pub/databases/GO/goa/HUMAN/goa_human.gaf.gz"

USER_AGENT = "bpgraph"
"""The CDN in front of the ontology answers `403` to urllib's own agent."""

TERM = "[Term]"
"""The only stanza kind that carries a term. The file ends with typedefs."""

IS_A = "is_a"
RELATIONSHIP = "relationship"
PART_OF = "part_of"
ALT_ID = "alt_id"
OBSOLETE = "is_obsolete"
TRUE = "true"
DANGLING = " ! "
"""OBO closes a reference with the target's name, for people to read."""

GAF_COMMENT = "!"
GAF_COLUMNS = 17

TERM_COLUMNS = ("go_id", "name", "namespace", "obsolete")
EDGE_COLUMNS = ("child_go_id", "parent_go_id", "relation")
ANNOTATION_COLUMNS = ("accession", "go_id", "evidence_code", "assigned_by", "qualifier")

UNKNOWN_REPORTED = 5
"""How many unrecognized terms a warning names before it gives up."""


class _Field(IntEnum):
    """The GAF 2.2 columns this repo keeps, by position.

    The file has seventeen and names none of them: it carries no header, so
    position is the whole contract. What is dropped is the gene symbol and
    product name — the export has its own — the taxon, which is human
    throughout, and the reference and date behind each annotation.
    """

    ACCESSION = 1
    QUALIFIER = 3
    GO_ID = 4
    EVIDENCE_CODE = 6
    ASSIGNED_BY = 14


@dataclass(frozen=True, slots=True, order=True)
class Annotation:
    """One GOA row, reduced to what docs/export.md asks of it.

    Several rows routinely differ only in the publication they cite, which the
    export format does not record, so what is left of them is one annotation —
    hence the ordering, which is what lets a set of these come out stable.
    """

    accession: str
    go_id: str
    evidence_code: str
    assigned_by: str
    qualifier: str


@dataclass(frozen=True, slots=True)
class Ontology:
    """`go-basic.obo`, reduced to terms and the two edges above them.

    `aliases` maps a term's secondary ids onto its primary one. GO keeps them
    forever as terms are merged, and GOA annotates whichever id was current
    when the annotation was made, so this is what stops an old annotation
    looking like a term the ontology does not have.
    """

    terms: Mapping[str, GoTerm]
    parents: Mapping[str, tuple[GoEdge, ...]]
    aliases: Mapping[str, str]

    def canonical(self, go_id: str) -> str | None:
        """The id this term is known by now, or nothing if GO never had it."""
        if go_id in self.terms:
            return go_id
        return self.aliases.get(go_id)

    def closure(self, go_ids: Iterable[str]) -> tuple[list[GoTerm], list[GoEdge]]:
        """These terms, everything above them, and the edges between.

        Walking up from the annotated terms rather than keeping the whole
        ontology is what keeps the graph to the part of GO this export can
        reach: some forty thousand terms describe things no human protein here
        is annotated with.
        """
        reached: set[str] = set()
        edges: set[GoEdge] = set()
        frontier = list(go_ids)
        while frontier:
            go_id = frontier.pop()
            if go_id in reached:
                continue
            reached.add(go_id)
            for edge in self.parents[go_id]:
                edges.add(edge)
                frontier.append(edge.parent_go_id)
        return (
            [self.terms[go_id] for go_id in sorted(reached)],
            sorted(edges, key=lambda e: (e.child_go_id, e.relation, e.parent_go_id)),
        )


def download(url: str, destination: Path) -> Path:
    """Fetch a dump into a run directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response, destination.open("wb") as handle:
        copyfileobj(response, handle)
    return destination


def cached(url: str, destination: Path) -> Path:
    """The local copy of a dump, fetched if it is not there yet.

    A run directory is new with every export, so the first fetch into it takes
    the current release, and every fetch after it reuses that one.
    """
    if not destination.exists():
        logger.info("go: fetching %s", url)
        download(url, destination)
    return destination


def _clean(text: str) -> str:
    """One line of text: the export holds no tab and no newline of its own."""
    return " ".join(text.split())


def _target(value: str) -> str:
    """An OBO reference, without the name OBO closes it with."""
    return value.split(DANGLING)[0].strip()


def _stanzas(path: Path) -> Iterator[tuple[str, Mapping[str, list[str]]]]:
    """The file's stanzas, each as its tag lines grouped by tag.

    A tag may repeat — `is_a` once per parent — so every one of them is a list.
    The header above the first stanza has no heading and is never yielded.
    """
    heading = ""
    fields: dict[str, list[str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("["):
                if heading:
                    yield heading, fields
                heading, fields = stripped, {}
            elif ": " in stripped:
                tag, _, value = stripped.partition(": ")
                fields.setdefault(tag, []).append(value.strip())
    if heading:
        yield heading, fields


def _parents(go_id: str, fields: Mapping[str, list[str]]) -> Iterator[GoEdge]:
    """The `is_a` and `part_of` edges out of one stanza.

    An obsolete term has neither: GO detaches a term from the ontology when it
    retires it, which is why an annotation to one rolls up to nothing.
    """
    for parent in fields.get(IS_A, ()):
        yield GoEdge(
            child_go_id=go_id,
            parent_go_id=_target(parent),
            relation=GoRelation.IS_A,
        )
    for relationship in fields.get(RELATIONSHIP, ()):
        relation, _, parent = relationship.partition(" ")
        if relation == PART_OF:
            yield GoEdge(
                child_go_id=go_id,
                parent_go_id=_target(parent),
                relation=GoRelation.PART_OF,
            )


def read_ontology(path: Path) -> Ontology:
    """Parse `go-basic.obo`. Terms only; the typedefs describe the relations."""
    terms: dict[str, GoTerm] = {}
    parents: dict[str, tuple[GoEdge, ...]] = {}
    aliases: dict[str, str] = {}
    for heading, fields in _stanzas(path):
        if heading != TERM:
            continue
        go_id = fields["id"][0]
        terms[go_id] = GoTerm(
            go_id=go_id,
            name=_clean(fields["name"][0]),
            namespace=GoNamespace(fields["namespace"][0]),
            obsolete=fields.get(OBSOLETE, ())[:1] == [TRUE],
        )
        parents[go_id] = tuple(_parents(go_id, fields))
        for alias in fields.get(ALT_ID, ()):
            aliases[alias] = go_id
    logger.info("go: %d terms in %s", len(terms), path)
    return Ontology(terms=terms, parents=parents, aliases=aliases)


def read_annotations(
    path: Path, accessions: Iterable[str], ontology: Ontology
) -> list[Annotation]:
    """The GOA rows about these proteins, one per distinct annotation.

    The dump is the whole human reference proteome, so everything the export
    does not name is dropped on the way past — as is an annotation to a term
    GO has since deleted outright, which would otherwise point at a node the
    ontology can no longer build.
    """
    wanted = set(accessions)
    annotations: set[Annotation] = set()
    unknown: Counter[str] = Counter()
    malformed = 0
    with gzip.open(path, mode="rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(GAF_COMMENT):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != GAF_COLUMNS:
                malformed += 1
                continue
            accession = fields[_Field.ACCESSION]
            if accession not in wanted:
                continue
            go_id = ontology.canonical(fields[_Field.GO_ID])
            if go_id is None:
                unknown[fields[_Field.GO_ID]] += 1
                continue
            annotations.add(
                Annotation(
                    accession=accession,
                    go_id=go_id,
                    evidence_code=fields[_Field.EVIDENCE_CODE],
                    assigned_by=_clean(fields[_Field.ASSIGNED_BY]),
                    qualifier=_clean(fields[_Field.QUALIFIER]),
                )
            )
    if malformed:
        logger.warning(
            "go: %d lines of %s do not have %d columns and were skipped",
            malformed,
            path.name,
            GAF_COLUMNS,
        )
    if unknown:
        logger.warning(
            "go: %d annotations name %d terms the ontology does not have (%s): "
            "the two dumps are of different releases",
            sum(unknown.values()),
            len(unknown),
            ", ".join(sorted(unknown)[:UNKNOWN_REPORTED]),
        )
    return sorted(annotations)


def _write(path: Path, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> int:
    """One file, written whole. Returns the rows written."""
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
            written += 1
    return written


@dataclass(frozen=True, slots=True)
class Counts:
    """What one run of the fetcher wrote."""

    terms: int
    edges: int
    annotations: int
    proteins: int
    """Proteins with at least one annotation, out of those asked for."""


def write_go(accessions: Iterable[str], run: Run) -> Counts:
    """Cut the GO these proteins reach out of the two dumps and write the trio.

    Everything is in hand before a file is opened, so a dump that gives out
    part way leaves whatever was there already rather than three files that
    disagree with each other.
    """
    paths = run.go
    parsed = read_ontology(cached(ONTOLOGY_URL, run.ontology))
    found = read_annotations(
        cached(ANNOTATIONS_URL, run.annotations), accessions, parsed
    )
    terms, edges = parsed.closure({annotation.go_id for annotation in found})
    return Counts(
        terms=_write(
            paths.terms,
            TERM_COLUMNS,
            (
                (
                    term.go_id,
                    term.name,
                    term.namespace.value,
                    str(term.obsolete).lower(),
                )
                for term in terms
            ),
        ),
        edges=_write(
            paths.edges,
            EDGE_COLUMNS,
            ((e.child_go_id, e.parent_go_id, e.relation.value) for e in edges),
        ),
        annotations=_write(
            paths.annotations,
            ANNOTATION_COLUMNS,
            (
                (a.accession, a.go_id, a.evidence_code, a.assigned_by, a.qualifier)
                for a in found
            ),
        ),
        proteins=len({annotation.accession for annotation in found}),
    )


def main() -> None:
    """Fetch the GO one run directory's human proteins reach.

    `uv run bpgraph-go data/2026-09-09` reads that run's export to learn which
    human proteins it names, cuts the ontology down to what they are annotated
    with and writes `go_terms.tsv`, `go_edges.tsv` and `go_annotations.tsv`
    beside it. Rebuilding is what puts them in the graph.
    """
    import sys

    from bpgraph.loaders import TsvExport

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-go <run directory>")
    loader = TsvExport.open(Path(sys.argv[1]))
    export = loader.load()
    humans = {
        protein.accession
        for protein in export.proteins
        if protein.kind is ProteinKind.HUMAN
    }
    counts = write_go(sorted(humans), loader.run)
    paths = loader.run.go
    print(
        f"{paths.terms}: {counts.terms} terms, {counts.edges} edges\n"
        f"{paths.annotations}: {counts.annotations} annotations on "
        f"{counts.proteins} of {len(humans)} human proteins"
    )
