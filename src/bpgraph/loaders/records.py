"""The records a build's intermediate files hold, one per line.

Each is a tuple of text, written as it is and read back with `of`, which skips
the key fields a sort put in front of it. A record whose file is sorted by its
own leading field needs no key in front: `Description` leads with its
interaction, `Report` too.
"""

from pathlib import Path
from typing import NamedTuple, Self

from bpgraph.files import Record
from bpgraph.loaders.tsv import Cursor


def of[T: tuple[str, ...]](kind: type[T], record: Record, width: int = 0) -> T:
    """A record read back from a file, skipping `width` key fields in front."""
    return kind(*record[width:])


class Curated(NamedTuple):
    """One row of the export's description files.

    `status` says what the build does with it: `kept`, or dropped because it
    names a human partner Swiss-Prot does not have (`absent`). A dropped row
    still answers for its peptides, which go with it.
    `partner_2` is the second partner's protein id: its accession if human,
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
    """One observation as the graph holds it. `stable_ids` are `;`-joined."""

    interaction_id: str
    id: str
    intact_id: str
    stable_ids: str
    kind: str
    side_a: str
    side_b: str
    pmid: str
    method_id: str
    method_name: str


class Report(NamedTuple):
    """A peptide one description reports, and the side it comes from."""

    interaction_id: str
    description_id: str
    sequence: str
    source_side: str


class Site(NamedTuple):
    """One entry and span a viral protein was observed at, and its residues."""

    protein_id: str
    virus_id: str
    name: str
    accession: str
    start: str
    stop: str
    strain_id: str
    strain_name: str
    sequence: str


class ViralProtein(NamedTuple):
    """A viral protein as the graph holds it. `description` and `function` hold
    every distinct text its entries carry, `\\x1f`-joined; `pmids` those the
    function texts cite, `;`-joined."""

    id: str
    virus_id: str
    name: str
    description: str
    function: str
    pmids: str


SEPARATOR = "\x1f"
"""Joins several texts in one field of an intermediate file."""
