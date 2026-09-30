"""IntAct's interactions of one host, filtered to what its network is built on.

IntAct publishes every interaction with a partner of a species as one MITAB 2.7
file — for human, a zip of over a gigabyte. It is streamed rather than
downloaded: the zip is inflated as it arrives and each row is filtered on the
way past, so only `intact.tsv` lands in the host's silo.

The graph is for an agent that explores it to formulate biological hypotheses,
such as mechanistic explanations. So an IntAct row is kept when it reports a
real interaction, observed by an experiment, in a publication:

- both partners are Swiss-Prot entries of the host, once an isoform or a chain
  is mapped to its entry;
- it cites exactly one PubMed id: the publication an agent reads;
- it is not a negative result;
- its detection method is flagged `keep` in `curation/methods.tsv`;
- no lower pmid of its group in `curation/publications.tsv` reports the same
  pair: a publication that re-reports an experiment adds only the pairs it is
  the first of its group to report.

A detection method with no row there fails the fetch, naming it, once the
whole file is read.

Spoke-expanded complexes are kept, so one IntAct interaction id may name
several rows, one per pair. Negative interactions are published apart and never
read; the `Negative` column is checked anyway.
"""

import logging
import re
import struct
import tempfile
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator
from enum import IntEnum
from pathlib import Path
from urllib.request import Request, urlopen

from bpgraph import files
from bpgraph.loaders.tsv import rows
from bpgraph.methods import Methods
from bpgraph.psimi import Ontology, read_ontology
from bpgraph.publications import read_groups
from bpgraph.run import HUMAN, HostPaths, Run
from bpgraph.sources import record_source
from bpgraph.swissprot import canonical

logger = logging.getLogger(__name__)

SPECIES_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/intact/current/psimitab/species/{}.zip"
)
SPECIES = {HUMAN: "human"}
"""IntAct's name for each host's file."""
RELEASES_URL = "https://ftp.ebi.ac.uk/pub/databases/intact/"
"""`current` names no release; the dated directory beside it does."""

UNIPROT = "uniprotkb:"
PUBMED = "pubmed:"
INTACT = "intact:"
PSIMI = re.compile(r'psi-mi:"(MI:\d{4})"')
RELEASE = re.compile(r'href="(\d{4}-\d{2}-\d{2})/"')
COLUMNS = ("intact_id", "accession1", "accession2", "pmid", "psimi_id")
MITAB_COLUMNS = 42

LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
LOCAL_SIGNATURE = 0x04034B50
DEFLATE = 8
CHUNK = 1 << 20


class _Field(IntEnum):
    """The MITAB 2.7 columns read here, by position."""

    ID_A = 0
    ID_B = 1
    METHOD = 6
    PUBLICATIONS = 8
    INTERACTION_IDS = 13
    NEGATIVE = 35


def _inflate(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """The first member of a zip, inflated as its bytes arrive.

    A zip names its members at the end, which a stream never reaches; the local
    header in front of each member says enough to read the first one.
    """
    stream = iter(chunks)
    buffer = b""
    while len(buffer) < LOCAL_HEADER.size:
        buffer += next(stream)
    header = LOCAL_HEADER.unpack_from(buffer)
    signature, method, name_length, extra_length = (
        header[0],
        header[3],
        header[9],
        header[10],
    )
    if signature != LOCAL_SIGNATURE or method != DEFLATE:
        raise ValueError("intact: not a deflated zip member")
    offset = LOCAL_HEADER.size + name_length + extra_length
    while len(buffer) < offset:
        buffer += next(stream)
    inflater = zlib.decompressobj(-zlib.MAX_WBITS)
    yield inflater.decompress(buffer[offset:])
    for chunk in stream:
        if inflater.eof:
            return
        yield inflater.decompress(chunk)
    yield inflater.flush()


def _lines(url: str) -> Iterator[str]:
    """The MITAB file's lines, streamed from the zip at `url`."""
    request = Request(url, headers={"User-Agent": "bpgraph"})
    with urlopen(request) as response:
        chunks = iter(lambda: response.read(CHUNK), b"")
        pending = b""
        for data in _inflate(chunks):
            pending += data
            *complete, pending = pending.split(b"\n")
            for line in complete:
                yield line.decode("utf-8")
        if pending:
            yield pending.decode("utf-8")


def _accession(identifier: str) -> str | None:
    return (
        canonical(identifier.removeprefix(UNIPROT))
        if identifier.startswith(UNIPROT)
        else None
    )


def _values(cell: str, prefix: str) -> list[str]:
    return [
        value.removeprefix(prefix)
        for value in cell.split("|")
        if value.startswith(prefix)
    ]


def _candidates(
    lines: Iterable[str],
    ontology: Ontology,
    methods: Methods,
    dropped: Counter[str],
    uncurated: set[str],
) -> Iterator[list[str]]:
    """The rows that pass every test a row can pass alone, keyed by their first
    partner: `[accession1, accession2, intact_id, pmid, psimi_id]`. Whether
    both partners are Swiss-Prot entries is for the merges that follow."""
    for line in lines:
        if line.startswith("#") or not line:
            continue
        fields = line.split("\t")
        if len(fields) != MITAB_COLUMNS:
            dropped["malformed"] += 1
            continue
        if fields[_Field.NEGATIVE] == "true":
            dropped["negative"] += 1
            continue
        a, b = _accession(fields[_Field.ID_A]), _accession(fields[_Field.ID_B])
        if a is None or b is None:
            dropped["not uniprot"] += 1
            continue
        pmids = [p for p in _values(fields[_Field.PUBLICATIONS], PUBMED) if p.isdigit()]
        if not pmids:
            dropped["no pubmed id"] += 1
            continue
        if len(set(pmids)) > 1:
            dropped["several pubmed ids"] += 1
            continue
        coded = PSIMI.findall(fields[_Field.METHOD])
        if len(coded) != 1:
            dropped["not one method"] += 1
            continue
        method = ontology.canonical(coded[0])
        if method is None:
            dropped["method not in psi-mi"] += 1
            continue
        keep = methods.keep(method)
        if keep is None:
            uncurated.add(method)
            continue
        if not keep:
            dropped[f"method not kept: {method} {ontology.terms[method].name}"] += 1
            continue
        ids = _values(fields[_Field.INTERACTION_IDS], INTACT)
        if len(ids) != 1:
            dropped["not one intact id"] += 1
            continue
        first, second = sorted((a, b))
        yield [first, second, ids[0], pmids[0], method]


def _on_swissprot(
    path: Path, proteins: Path, dropped: Counter[str]
) -> Iterator[list[str]]:
    """The rows of a file keyed by an accession whose accession is a Swiss-Prot
    entry, with that accession rotated to the end: the next key comes first."""
    for _, found, entry in files.cogroup(files.read(path), files.read(proteins), 1):
        if entry:
            yield from (row[1:] + row[:1] for row in found)
        else:
            dropped["not swiss-prot of the host"] += len(found)


def _unrepeated(
    path: Path, groups: dict[str, str], dropped: Counter[str]
) -> Iterator[list[str]]:
    """The rows of a file sorted by pair, `[a, b, pmid, intact_id, method]`,
    read pair by pair in ascending pmid: a pair stays on the first pmid of each
    group that reports it."""
    for _, found in files.groups(files.read(path), 2):
        first: dict[str, str] = {}
        for a, b, pmid, intact_id, method in sorted(found, key=lambda r: int(r[2])):
            group = groups.get(pmid)
            if group and first.setdefault(group, pmid) != pmid:
                dropped[f"repeated in group {group}: {pmid}"] += 1
                continue
            yield [intact_id, a, b, pmid, method]


def _release() -> str:
    """The most recent dated release beside `current`."""
    request = Request(RELEASES_URL, headers={"User-Agent": "bpgraph"})
    with urlopen(request) as response:
        return max(RELEASE.findall(response.read().decode("utf-8")), default="")


def write_intact(
    host: HostPaths, psimi: Path, sources: Path
) -> tuple[int, Counter[str]]:
    """Stream, filter and write one host's `intact.tsv`. Returns the rows
    written and the count dropped per reason."""
    ontology = read_ontology(psimi)
    methods = Methods.load(ontology)
    groups = read_groups()
    uncurated: set[str] = set()
    release = _release()
    url = SPECIES_URL.format(SPECIES[host.taxon_id])
    logger.info("intact: streaming %s", url)
    dropped: Counter[str] = Counter()
    with tempfile.TemporaryDirectory(dir=host.directory) as directory:
        scratch = Path(directory)
        proteins = files.sorted_file(
            scratch / "proteins", ([r["accession"]] for _, r in rows(host.swissprot))
        )
        first = files.sorted_file(
            scratch / "first",
            _candidates(_lines(url), ontology, methods, dropped, uncurated),
        )
        if uncurated:
            methods.check(uncurated)
        second = files.sorted_file(
            scratch / "second", _on_swissprot(first, proteins, dropped)
        )
        pairs = files.sorted_file(
            scratch / "pairs",
            (
                [a, b, pmid, intact_id, method]
                for intact_id, pmid, method, a, b in _on_swissprot(
                    second, proteins, dropped
                )
            ),
            unique=True,
        )
        both = files.sorted_file(
            scratch / "both", _unrepeated(pairs, groups, dropped), unique=True
        )
        written = files.write_table(host.intact, COLUMNS, files.read(both))
    record_source(sources, f"{host.taxon_id} intact", url, release)
    return written, dropped


def main() -> None:
    """Filter IntAct into one run directory.

    `uv run bpgraph-intact data/2026-09-09` needs `psi-mi.obo` and
    `hosts/9606/swissprot.tsv` there first, and writes `hosts/9606/intact.tsv`.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-intact <run directory>")
    run = Run(Path(sys.argv[1]))
    host = run.host(HUMAN)
    written, dropped = write_intact(host, run.psimi, run.sources)
    for reason, count in dropped.most_common():
        print(f"dropped {count}: {reason}")
    print(f"{host.intact}: {written} rows")
