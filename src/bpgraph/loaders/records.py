"""The records a build's intermediate files hold, one per line.

Each is a tuple of text, written as it is and read back with `of`, which skips
the key fields a sort put in front of it. A record whose file is sorted by its
own leading field needs no key in front: `Description` leads with its
interaction, `Report` too.

Rows refer to a protein by a reference: a human protein's accession, a viral
protein's virus and name joined by `viral_ref`. A reference only ties rows of
these files together; it is never written to the graph, where a protein is
found by its own properties.
"""

from pathlib import Path
from typing import NamedTuple, Self

from bpgraph.files import Record
from bpgraph.loaders.tsv import Cursor


def viral_ref(virus_id: int | str, name: str) -> str:
    """A viral protein's reference in the build's files."""
    return f"{virus_id}:{name}"


def pair_ref(a: str, b: str) -> str:
    """An interaction's reference in the build's files: its two proteins'."""
    return f"{a}|{b}"


def of[T: tuple[str, ...]](kind: type[T], record: Record, width: int = 0) -> T:
    """A record read back from a file, skipping `width` key fields in front."""
    return kind(*record[width:])


class Curated(NamedTuple):
    """One row of the export's description files.

    `status` says what the build does with it: `kept`, or dropped because it
    names a human partner Swiss-Prot does not have (`absent`). A dropped row
    still answers for its peptides, which go with it.
    `partner_2` is the second partner's reference: its accession if human,
    its curated virus and name if viral, which `strain_id` and `strain_name`
    then place in the taxonomy.
    """

    stable_id: str
    kind: str
    status: str
    pmid: str
    psimi_id: str
    accession_1: str
    accession_2: str
    start_2: str
    stop_2: str
    name_2: str
    taxon_2: str
    partner_2: str
    strain_id: str
    strain_name: str
    path: str
    line: str

    @property
    def cursor(self) -> Cursor:
        return Cursor(Path(self.path), int(self.line))

    @property
    def site_2(self) -> tuple[str, str, str]:
        return (self.accession_2, self.start_2, self.stop_2)

    def with_status(self, status: str) -> Self:
        return self._replace(status=status)


KEPT = "kept"
ABSENT = "absent"


class Description(NamedTuple):
    """One observation: a pair, a publication and a method. `stable_id` is our
    curated row's, or `''` for an IntAct record we have not curated. `side_a`
    is the human protein of a VH pair, the one sorting first of an HH pair."""

    interaction: str
    kind: str
    side_a: str
    side_b: str
    pmid: str
    method_id: str
    method_name: str
    stable_id: str


class Report(NamedTuple):
    """A peptide one curated description reports: the protein it was cut
    from, and the one it binds."""

    interaction: str
    stable_id: str
    sequence: str
    source: str
    target: str


class Site(NamedTuple):
    """One entry and span a viral protein was observed at, and its residues."""

    ref: str
    virus_id: str
    name: str
    accession: str
    start: str
    stop: str
    strain_id: str
    strain_name: str
    sequence: str


class ViralProtein(NamedTuple):
    """A viral protein as the graph holds it. `function` holds every distinct
    text its entries carry, `\\x1f`-joined; `pmids` those the texts cite,
    `;`-joined. `ref` is its reference in the build's files."""

    ref: str
    virus_id: str
    name: str
    function: str
    pmids: str


SEPARATOR = "\x1f"
"""Joins several texts in one field of an intermediate file."""
