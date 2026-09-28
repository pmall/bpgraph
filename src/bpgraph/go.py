"""The Gene Ontology, and a host's experimental GO annotations.

Two dumps, both streamed from the network and neither kept: the ontology,
`go-basic.obo`, and the host's GOA annotations. What the host's silo keeps is
exactly what the build writes:

- `go_annotations.tsv`, the annotations the graph takes;
- `go_terms.tsv`, every term they reach, with its ancestors;
- `go_edges.tsv`, the `is_a` and `part_of` edges between those terms.

**Experimental evidence only**, each citing a PubMed id: `EXP`, `IDA`, `IPI`,
`IMP`, `IGI`, `IEP` and their high-throughput counterparts. An experiment is
what gives an annotation a publication, and a publication is what an agent can
read. Electronic and inferred annotations add no publication, and restate what
other annotations say. A GOA row citing several pmids is one annotation per
pmid, as an interaction observation is one description per publication.

- **`go-basic.obo`** is the release filtered to the relations annotations
  propagate over and guaranteed acyclic, which is exactly the traversal the
  schema promises. Of the relations it keeps, only `is_a` and `part_of` are
  modelled: the three `regulates` relations propagate nothing, since a protein
  involved in `regulation of X` is not involved in `X`.
- **GOA** is every GO annotation on the host's reference proteome, with the
  evidence code, the qualifier, the assigning database and the references.
  Everything not on a Swiss-Prot entry of the host is dropped. GOA annotates
  whichever id a term had when the annotation was made, so a secondary id is
  mapped onto the term's current one, and a term GO has deleted outright drops
  its annotation.

**Host proteins only.** GOA does annotate viral proteins, but it annotates a
whole accession, while a viral protein here is one mature chain excised from a
polyprotein and nothing in GOA says which chain a term belongs to.

An annotation is made to the most specific term that fits, so the silo keeps
the **full ancestor closure** above every annotated term, walked up one level
at a time on disk.
"""

import gzip
import io
import logging
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from enum import IntEnum
from pathlib import Path
from urllib.request import Request, urlopen

from bpgraph import files
from bpgraph.enums import GoNamespace, GoRelation
from bpgraph.loaders.tsv import rows
from bpgraph.obo import TERM, parse, target
from bpgraph.run import HUMAN, HostPaths, Run
from bpgraph.sources import record_source

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
VERSION = "data-version:"
GENERATED = "!date-generated:"

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
TERM_COLUMNS = ("go_id", "name", "namespace", "obsolete")
EDGE_COLUMNS = ("child_go_id", "parent_go_id", "relation")

UNKNOWN_REPORTED = 5
"""How many unrecognized terms a warning names before it gives up."""


class _Field(IntEnum):
    ACCESSION = 1
    QUALIFIER = 3
    GO_ID = 4
    REFERENCE = 5
    EVIDENCE_CODE = 6
    ASSIGNED_BY = 14


def _clean(text: str) -> str:
    """One line of text: a TSV cell holds no tab and no newline."""
    return " ".join(text.split())


def _lines(url: str) -> Iterator[str]:
    """A text file's lines, streamed, gunzipped if the URL says so."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        raw = gzip.GzipFile(fileobj=response) if url.endswith(".gz") else response
        yield from io.TextIOWrapper(raw, encoding="utf-8")


class _Header:
    """Passes lines through, remembering the release a dump's header names."""

    def __init__(self, lines: Iterable[str], tag: str) -> None:
        self.lines, self.tag, self.release = lines, tag, ""

    def __iter__(self) -> Iterator[str]:
        for line in self.lines:
            if not self.release and line.startswith(self.tag):
                self.release = line.removeprefix(self.tag).strip()
            yield line


def _ontology(scratch: Path) -> tuple[Path, Path, Path, str]:
    """Stream the ontology into three sorted files: its terms, every id a
    term answers to (its own and its secondary ones) with that term, and its
    edges keyed by child. Returns them and the release."""
    terms, ids, edges = scratch / "terms", scratch / "ids", scratch / "edges"
    header = _Header(_lines(ONTOLOGY_URL), VERSION)
    with (
        terms.open("w", encoding="utf-8") as t,
        ids.open("w", encoding="utf-8") as i,
        edges.open("w", encoding="utf-8") as e,
    ):
        for heading, fields in parse(header):
            if heading != TERM:
                continue
            go_id = fields["id"][0]
            obsolete = fields.get(OBSOLETE, ())[:1] == [TRUE]
            namespace = GoNamespace(fields["namespace"][0]).value
            t.write(f"{go_id}\t{_clean(fields['name'][0])}\t{namespace}\t{obsolete}\n")
            for alias in (go_id, *fields.get(ALT_ID, ())):
                i.write(f"{alias}\t{go_id}\n")
            for parent in fields.get(IS_A, ()):
                e.write(f"{go_id}\t{target(parent)}\t{GoRelation.IS_A.value}\n")
            for relationship in fields.get(RELATIONSHIP, ()):
                relation, _, parent = relationship.partition(" ")
                if relation == PART_OF:
                    e.write(f"{go_id}\t{target(parent)}\t{GoRelation.PART_OF.value}\n")
    for path in (terms, ids, edges):
        files.sort(path, unique=True)
    return terms, ids, edges, header.release


def _candidates(lines: Iterable[str], dropped: Counter[str]) -> Iterator[list[str]]:
    """GOA rows that are experimental and cite PubMed, one per pmid, keyed by
    the term id as GOA gives it."""
    for line in lines:
        if line.startswith(GAF_COMMENT):
            continue
        fields = line.rstrip("\n").split("\t")
        if len(fields) != GAF_COLUMNS:
            dropped["malformed"] += 1
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
        for pmid in pmids:
            yield [
                fields[_Field.GO_ID],
                fields[_Field.ACCESSION],
                _clean(fields[_Field.QUALIFIER]),
                fields[_Field.EVIDENCE_CODE],
                _clean(fields[_Field.ASSIGNED_BY]),
                pmid,
            ]


def _annotations(
    host: HostPaths, ids: Path, scratch: Path, dropped: Counter[str]
) -> tuple[Path, str]:
    """The host's annotations, on current terms and Swiss-Prot entries,
    distinct, as a sorted file keyed by accession. Returns it and the release."""
    url = ANNOTATIONS_URL.format(*GOA_SPECIES[host.taxon_id])
    logger.info("go: streaming %s", url)
    header = _Header(_lines(url), GENERATED)
    by_term = files.sorted_file(scratch / "by_term", _candidates(header, dropped))

    unknown: Counter[str] = Counter()

    def current() -> Iterator[list[str]]:
        for (go_id,), found, aliases in files.cogroup(
            files.read(by_term), files.read(ids), 1
        ):
            if not aliases:
                unknown[go_id] += len(found)
                dropped["term not in the ontology"] += len(found)
                continue
            primary = aliases[0][1]
            for _, accession, *rest in found:
                yield [accession, primary, *rest]

    by_accession = files.sorted_file(scratch / "by_accession", current())
    if unknown:
        logger.warning(
            "go: %d annotations name %d terms the ontology does not have (%s): "
            "the two dumps are of different releases",
            sum(unknown.values()),
            len(unknown),
            ", ".join(sorted(unknown)[:UNKNOWN_REPORTED]),
        )
    proteins = files.sorted_file(
        scratch / "proteins",
        ([row["accession"]] for _, row in rows(host.swissprot)),
    )

    def on_swissprot() -> Iterator[list[str]]:
        for _, found, entry in files.cogroup(
            files.read(by_accession), files.read(proteins), 1
        ):
            if entry:
                yield from found
            else:
                dropped["not swiss-prot of the host"] += len(found)

    return files.sorted_file(scratch / "annotations", on_swissprot(), unique=True), (
        header.release
    )


def _closure(annotated: Path, edges: Path, scratch: Path) -> tuple[Path, Path]:
    """The annotated terms and everything above them, and the edges walked to
    reach them, one level at a time: each round follows the edges out of the
    terms the last round reached for the first time."""
    reached = files.sorted_file(scratch / "reached", files.read(annotated), unique=True)
    frontier = files.sorted_file(scratch / "frontier", files.read(reached))
    walked = scratch / "walked"
    walked.touch()
    while True:
        parents = scratch / "parents"
        with walked.open("a", encoding="utf-8") as out:

            def up() -> Iterator[list[str]]:
                for _, children, found in files.cogroup(
                    files.read(frontier), files.read(edges), 1
                ):
                    if children:
                        for child, parent, relation in found:
                            out.write(f"{child}\t{parent}\t{relation}\n")
                            yield [parent]

            files.sorted_file(parents, up(), unique=True)
        new = files.sorted_file(
            scratch / "new",
            (
                list(key)
                for key, above, known in files.cogroup(
                    files.read(parents), files.read(reached), 1
                )
                if above and not known
            ),
        )
        if new.stat().st_size == 0:
            break
        files.sorted_file(
            scratch / "union",
            (
                list(key)
                for key, _, _ in files.cogroup(files.read(reached), files.read(new), 1)
            ),
        ).replace(reached)
        new.replace(frontier)
    return reached, files.sort(walked, unique=True)


def write_go(host: HostPaths, sources: Path) -> tuple[int, int, int, Counter[str]]:
    """Fetch GO and GOA and write the host's three files. Returns the
    annotations, terms and edges written, and the GOA rows dropped per reason."""
    dropped: Counter[str] = Counter()
    with tempfile.TemporaryDirectory(dir=host.directory) as directory:
        scratch = Path(directory)
        logger.info("go: streaming %s", ONTOLOGY_URL)
        terms, ids, edges, go_release = _ontology(scratch)
        annotations, goa_release = _annotations(host, ids, scratch, dropped)
        annotated = files.sorted_file(
            scratch / "annotated", ([r[1]] for r in files.read(annotations))
        )
        reached, walked = _closure(annotated, edges, scratch)
        n_annotations = files.write_table(
            host.go_annotations, ANNOTATION_COLUMNS, files.read(annotations)
        )
        n_terms = files.write_table(
            host.go_terms,
            TERM_COLUMNS,
            (
                term[0]
                for _, wanted, term in files.cogroup(
                    files.read(reached), files.read(terms), 1
                )
                if wanted and term
            ),
        )
        n_edges = files.write_table(host.go_edges, EDGE_COLUMNS, files.read(walked))
    record_source(sources, "go", ONTOLOGY_URL, go_release)
    record_source(
        sources,
        f"{host.taxon_id} goa",
        ANNOTATIONS_URL.format(*GOA_SPECIES[host.taxon_id]),
        goa_release,
    )
    return n_annotations, n_terms, n_edges, dropped


def main() -> None:
    """Fetch GO and one host's experimental annotations.

    `uv run bpgraph-go data/2026-09-09` needs `hosts/9606/swissprot.tsv` first,
    and writes `go_annotations.tsv`, `go_terms.tsv` and `go_edges.tsv` there.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-go <run directory>")
    run = Run(Path(sys.argv[1]))
    host = run.host(HUMAN)
    annotations, terms, edges, dropped = write_go(host, run.sources)
    for reason, count in dropped.most_common():
        print(f"dropped {count}: {reason}")
    print(f"{host.directory}: {annotations} annotations, {terms} terms, {edges} edges")
