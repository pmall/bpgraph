"""IntAct's human interactions, filtered to what the HH network is built on.

IntAct publishes every interaction with a human partner as one MITAB 2.7 file
in a zip of over a gigabyte. It is streamed rather than downloaded: the zip is
inflated as it arrives and each row is filtered on the way past, so only
`intact.tsv` lands in the run directory.

A row is kept when:

- both partners are UniProt entries of Swiss-Prot human, once an isoform or a
  chain is mapped to its entry;
- it cites a PubMed id;
- its detection method is experimental — not under `MI:0364` (inferred by
  curator) nor `MI:0063` (interaction prediction).

Every interaction type is kept, association and colocalization included: what
makes a row evidence here is the experiment behind it. The types kept are
logged.

Spoke-expanded complexes are kept, so one IntAct interaction id may name
several rows, one per pair. Negative interactions are published apart and never
read; the `Negative` column is checked anyway.
"""

import logging
import re
import struct
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from urllib.request import Request, urlopen

from bpgraph.psimi import Ontology, read_ontology
from bpgraph.run import Run
from bpgraph.sources import record_source
from bpgraph.swissprot import canonical, iter_accessions

logger = logging.getLogger(__name__)

URL = "https://ftp.ebi.ac.uk/pub/databases/intact/current/psimitab/species/human.zip"
RELEASES_URL = "https://ftp.ebi.ac.uk/pub/databases/intact/"
"""`current` names no release; the dated directory beside it does."""

NOT_EXPERIMENTAL = ("MI:0364", "MI:0063")

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
    TYPE = 11
    INTERACTION_IDS = 13
    NEGATIVE = 35


@dataclass(frozen=True, slots=True, order=True)
class Row:
    intact_id: str
    accession1: str
    accession2: str
    pmid: int
    psimi_id: str


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


def filter_rows(
    lines: Iterable[str], humans: frozenset[str], ontology: Ontology
) -> tuple[list[Row], Counter[str]]:
    """The rows kept, and why the others were dropped."""
    dropped: Counter[str] = Counter()
    types: Counter[str] = Counter()
    kept: set[Row] = set()
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
        if a is None or b is None or a not in humans or b not in humans:
            dropped["not swiss-prot human"] += 1
            continue
        pmids = [p for p in _values(fields[_Field.PUBLICATIONS], PUBMED) if p.isdigit()]
        if not pmids:
            dropped["no pubmed id"] += 1
            continue
        if len(set(pmids)) > 1:
            dropped["several pubmed ids"] += 1
            continue
        methods = PSIMI.findall(fields[_Field.METHOD])
        if len(methods) != 1:
            dropped["not one method"] += 1
            continue
        method = ontology.canonical(methods[0])
        if method is None:
            dropped["method not in psi-mi"] += 1
            continue
        if ontology.under(method, NOT_EXPERIMENTAL):
            dropped["not experimental"] += 1
            continue
        ids = _values(fields[_Field.INTERACTION_IDS], INTACT)
        if len(ids) != 1:
            dropped["not one intact id"] += 1
            continue
        first, second = sorted((a, b))
        kept.add(Row(ids[0], first, second, int(pmids[0]), method))
        types[fields[_Field.TYPE]] += 1
    for kind, count in types.most_common():
        logger.info("intact: kept %d rows of type %s", count, kind)
    return sorted(kept), dropped


def _release() -> str:
    """The most recent dated release beside `current`."""
    request = Request(RELEASES_URL, headers={"User-Agent": "bpgraph"})
    with urlopen(request) as response:
        return max(RELEASE.findall(response.read().decode("utf-8")), default="")


def write_intact(run: Run) -> tuple[int, Counter[str]]:
    """Stream, filter and write `intact.tsv`. Returns the rows written and the
    count dropped per reason."""
    humans = frozenset(iter_accessions(run.swissprot))
    ontology = read_ontology(run.psimi)
    release = _release()
    logger.info("intact: streaming %s", URL)
    rows, dropped = filter_rows(_lines(URL), humans, ontology)
    with run.intact.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write(
                f"{row.intact_id}\t{row.accession1}\t{row.accession2}\t{row.pmid}\t{row.psimi_id}\n"
            )
    record_source(run.sources, "intact", URL, release)
    return len(rows), dropped


def main() -> None:
    """Filter IntAct into one run directory.

    `uv run bpgraph-intact data/2026-09-09` needs `psi-mi.obo` and
    `swissprot_human.tsv` there first, and writes `intact.tsv`.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-intact <run directory>")
    run = Run(Path(sys.argv[1]))
    written, dropped = write_intact(run)
    for reason, count in dropped.most_common():
        print(f"dropped {count}: {reason}")
    print(f"{run.intact}: {written} rows")
