"""The Gene Ontology, and a host's experimental GO annotations.

Two dumps: the ontology, shared by every silo and fetched to the top of the run
directory, and the host's GOA annotations, fetched into its silo. This module
cuts the second to what the graph takes, `go_annotations.tsv`; the build reads
the ontology itself, and keeps the terms those annotations reach.

**Experimental evidence only**, each citing a PubMed id: `EXP`, `IDA`, `IPI`,
`IMP`, `IGI`, `IEP` and their high-throughput counterparts. An experiment is
what gives an annotation a publication, and a publication is what an agent can
read. Electronic and inferred annotations add no publication, and restate what
other annotations say. A GOA row citing several pmids is one annotation per
pmid, as an interaction observation is one description per publication.

- **`go-basic.obo`** is the ontology. It is the release filtered to the
  relations annotations propagate over and guaranteed acyclic, which is exactly
  the traversal the schema promises. Of the relations it keeps, only `is_a` and
  `part_of` are modelled: the three `regulates` relations propagate nothing,
  since a protein involved in `regulation of X` is not involved in `X`.
- **`goa.gaf.gz`** is every GO annotation on the host's reference proteome,
  with the evidence code, the qualifier, the assigning database and the
  references. Everything not on a Swiss-Prot entry of the host is dropped on
  the way past.

**Host proteins only.** GOA does annotate viral proteins, but it annotates a
whole accession, while a viral protein here is one mature chain excised from a
polyprotein and nothing in GOA says which chain a term belongs to.

An annotation is made to the most specific term that fits, so the build loads
the **full ancestor closure** above every annotated term as well.
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

from bpgraph.enums import GoNamespace, GoRelation
from bpgraph.models import GoEdge, GoTerm
from bpgraph.obo import TERM, stanzas, target
from bpgraph.run import HUMAN, HostPaths, Run
from bpgraph.sources import record_source
from bpgraph.swissprot import iter_accessions

logger = logging.getLogger(__name__)

ONTOLOGY_URL = "https://purl.obolibrary.org/obo/go/go-basic.obo"
ANNOTATIONS_URL = "https://ftp.ebi.ac.uk/pub/databases/GO/goa/{0}/goa_{1}.gaf.gz"
GOA_SPECIES = {HUMAN: ("HUMAN", "human")}
"""GOA's directory and file name for each host."""

EXPERIMENTAL = frozenset(
    {"EXP", "IDA", "IPI", "IMP", "IGI", "IEP", "HTP", "HDA", "HMP", "HGI", "HEP"}
)
"""GO's experimental evidence codes, high-throughput ones included."""

PMID = "PMID:"

USER_AGENT = "bpgraph"
"""The CDN in front of the ontology answers `403` to urllib's own agent."""

IS_A = "is_a"
RELATIONSHIP = "relationship"
PART_OF = "part_of"
ALT_ID = "alt_id"
OBSOLETE = "is_obsolete"
TRUE = "true"

GAF_COMMENT = "!"
GAF_COLUMNS = 17

ANNOTATION_COLUMNS = (
    "accession",
    "go_id",
    "qualifier",
    "evidence_code",
    "assigned_by",
    "pmid",
)

UNKNOWN_REPORTED = 5
"""How many unrecognized terms a warning names before it gives up."""


class _Field(IntEnum):
    """The GAF 2.2 columns this repo keeps, by position.

    The file has seventeen and names none of them: it carries no header, so
    position is the whole contract. What is dropped is the gene symbol and
    product name — Swiss-Prot has its own — the taxon, which is the host's
    throughout, and the date.
    """

    ACCESSION = 1
    QUALIFIER = 3
    GO_ID = 4
    REFERENCE = 5
    EVIDENCE_CODE = 6
    ASSIGNED_BY = 14


@dataclass(frozen=True, slots=True, order=True)
class Annotation:
    """One GOA row and one pmid it cites, reduced to what the graph keeps.

    Rows differing only in what the graph does not keep — the date, the
    `with` column, an extension — are one annotation; hence the ordering,
    which is what lets a set of these come out stable.
    """

    accession: str
    go_id: str
    qualifier: str
    evidence_code: str
    assigned_by: str
    pmid: str


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


def _release(path: Path) -> str:
    """The release a dump names in its header: `data-version` in the ontology,
    `date-generated` in the annotations."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, mode="rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith(("!", "format-version", "data-version")):
                break
            for tag in ("data-version:", "!date-generated:"):
                if line.startswith(tag):
                    return line.removeprefix(tag).strip()
    return ""


def download(url: str, destination: Path) -> Path:
    """Fetch a dump into a run directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response, destination.open("wb") as handle:
        copyfileobj(response, handle)
    return destination


def _clean(text: str) -> str:
    """One line of text: the export holds no tab and no newline of its own."""
    return " ".join(text.split())


def _parents(go_id: str, fields: Mapping[str, list[str]]) -> Iterator[GoEdge]:
    """The `is_a` and `part_of` edges out of one stanza.

    An obsolete term has neither: GO detaches a term from the ontology when it
    retires it, which is why an annotation to one rolls up to nothing.
    """
    for parent in fields.get(IS_A, ()):
        yield GoEdge(
            child_go_id=go_id,
            parent_go_id=target(parent),
            relation=GoRelation.IS_A,
        )
    for relationship in fields.get(RELATIONSHIP, ()):
        relation, _, parent = relationship.partition(" ")
        if relation == PART_OF:
            yield GoEdge(
                child_go_id=go_id,
                parent_go_id=target(parent),
                relation=GoRelation.PART_OF,
            )


def read_ontology(path: Path) -> Ontology:
    """Parse `go-basic.obo`. Terms only; the typedefs describe the relations."""
    terms: dict[str, GoTerm] = {}
    parents: dict[str, tuple[GoEdge, ...]] = {}
    aliases: dict[str, str] = {}
    for heading, fields in stanzas(path):
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
) -> tuple[list[Annotation], Counter[str]]:
    """The experimental, PubMed-cited GOA rows about these proteins, one per
    distinct annotation and pmid, and how many rows were dropped and why.

    An annotation to a term GO has since deleted outright is dropped too: it
    would point at a node the ontology can no longer build.
    """
    wanted = set(accessions)
    annotations: set[Annotation] = set()
    dropped: Counter[str] = Counter()
    unknown: Counter[str] = Counter()
    with gzip.open(path, mode="rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith(GAF_COMMENT):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) != GAF_COLUMNS:
                dropped["malformed"] += 1
                continue
            accession = fields[_Field.ACCESSION]
            if accession not in wanted:
                dropped["not swiss-prot of the host"] += 1
                continue
            if fields[_Field.EVIDENCE_CODE] not in EXPERIMENTAL:
                dropped["not experimental"] += 1
                continue
            pmids = [
                reference.removeprefix(PMID)
                for reference in fields[_Field.REFERENCE].split("|")
                if reference.startswith(PMID) and reference[len(PMID) :].isdigit()
            ]
            if not pmids:
                dropped["no pubmed id"] += 1
                continue
            go_id = ontology.canonical(fields[_Field.GO_ID])
            if go_id is None:
                unknown[fields[_Field.GO_ID]] += 1
                dropped["term not in the ontology"] += 1
                continue
            annotations.update(
                Annotation(
                    accession=accession,
                    go_id=go_id,
                    qualifier=_clean(fields[_Field.QUALIFIER]),
                    evidence_code=fields[_Field.EVIDENCE_CODE],
                    assigned_by=_clean(fields[_Field.ASSIGNED_BY]),
                    pmid=pmid,
                )
                for pmid in pmids
            )
    if unknown:
        logger.warning(
            "go: %d annotations name %d terms the ontology does not have (%s): "
            "the two dumps are of different releases",
            sum(unknown.values()),
            len(unknown),
            ", ".join(sorted(unknown)[:UNKNOWN_REPORTED]),
        )
    return sorted(annotations), dropped


def _write(path: Path, columns: Sequence[str], rows: Iterable[Sequence[str]]) -> int:
    """One file, written whole. Returns the rows written."""
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(columns) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
            written += 1
    return written


def read_annotations_file(path: Path) -> list[Annotation]:
    """`go_annotations.tsv`, as written by `write_annotations`."""
    with path.open(encoding="utf-8") as handle:
        header = next(handle).rstrip("\n").split("\t")
        if tuple(header) != ANNOTATION_COLUMNS:
            raise ValueError(
                f"{path.name}: columns are {header}, not {ANNOTATION_COLUMNS}"
            )
        return [
            Annotation(*line.rstrip("\n").split("\t"))
            for line in handle
            if line.strip()
        ]


def fetch_ontology(run: Run) -> Path:
    """Download the ontology into a run directory, unless it is there already."""
    if not run.ontology.exists():
        logger.info("go: fetching %s", ONTOLOGY_URL)
        release = _release(download(ONTOLOGY_URL, run.ontology))
        record_source(run.sources, "go", ONTOLOGY_URL, release)
    return run.ontology


def write_annotations(
    host: HostPaths, ontology: Ontology, sources: Path
) -> tuple[int, int, Counter[str]]:
    """Cut the host's experimental annotations out of its GOA dump and write
    them. Returns the annotations written, the proteins they cover, and the
    rows dropped per reason.

    A run directory is new with every export, so the first fetch into it takes
    the current release, and every fetch after it reuses that one.
    """
    if not host.gaf.exists():
        url = ANNOTATIONS_URL.format(*GOA_SPECIES[host.taxon_id])
        logger.info("go: fetching %s", url)
        release = _release(download(url, host.gaf))
        record_source(sources, f"{host.taxon_id} goa", url, release)
    found, dropped = read_annotations(
        host.gaf, iter_accessions(host.swissprot), ontology
    )
    written = _write(
        host.go_annotations,
        ANNOTATION_COLUMNS,
        (
            (a.accession, a.go_id, a.qualifier, a.evidence_code, a.assigned_by, a.pmid)
            for a in found
        ),
    )
    return written, len({annotation.accession for annotation in found}), dropped


def main() -> None:
    """Fetch GO and one host's experimental annotations.

    `uv run bpgraph-go data/2026-09-09` fetches `go-basic.obo` into the run
    directory and GOA into `hosts/9606/`, and writes
    `hosts/9606/go_annotations.tsv`. Rebuilding is what puts them in the graph.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-go <run directory>")
    run = Run(Path(sys.argv[1]))
    host = run.host(HUMAN)
    ontology = read_ontology(fetch_ontology(run))
    written, proteins, dropped = write_annotations(host, ontology, run.sources)
    for reason, count in dropped.most_common():
        print(f"dropped {count}: {reason}")
    print(f"{host.go_annotations}: {written} annotations on {proteins} proteins")
