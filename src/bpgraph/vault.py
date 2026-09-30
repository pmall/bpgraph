"""The sequence vaults: SQLite files beside the graph, one per silo.

Sequences are kept out of the graph on purpose. Technically, so the graph stays
small enough to traverse; methodologically, so they are never the basis of
large-scale reasoning, only of the deep verification of one hypothesis. The
question a vault answers is about one protein at a time, never many.

- **A host vault**, `host-9606.sqlite`: every Swiss-Prot entry of the host, by
  accession — which is the host protein's id.
- **The viral vault**, `viral.sqlite`: every viral entry once, with its strain,
  and the mature proteins observed on them, each with the sequence curation
  recorded. A viral protein (`10407:HBx`) is pooled over strains and entries,
  so it has as many sequences as places it was observed at. The vault also
  keeps which entry each VH description used, which the graph no longer holds.

A build writes the vaults into its run, from the same run as the graph, and
publishes them once the graph is swapped: copies them to the live vault
directory, `BPGRAPH_VAULT`, where the API reads them, each replaced whole.
"""

import shutil
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

VIRAL_FILE = "viral.sqlite"


def host_file(taxon_id: int) -> str:
    """The file name of a host's vault."""
    return f"host-{taxon_id}.sqlite"


HOST_SCHEMA = (
    "CREATE TABLE sequence (accession TEXT PRIMARY KEY, sequence TEXT NOT NULL)",
)

VIRAL_SCHEMA = (
    """CREATE TABLE entry (
        accession   TEXT PRIMARY KEY,
        taxon_id    INTEGER NOT NULL,
        taxon_name  TEXT NOT NULL,
        description TEXT NOT NULL
    )""",
    """CREATE TABLE mature (
        protein_id TEXT NOT NULL,
        accession  TEXT NOT NULL REFERENCES entry (accession),
        start      INTEGER NOT NULL,
        stop       INTEGER NOT NULL,
        sequence   TEXT NOT NULL,
        PRIMARY KEY (protein_id, accession, start, stop)
    )""",
    """CREATE TABLE observation (
        description_id TEXT PRIMARY KEY,
        accession      TEXT NOT NULL REFERENCES entry (accession)
    )""",
)
"""`description` is UniProt's protein name, empty for an entry UniProt has
retired."""


@dataclass(frozen=True, slots=True)
class MatureSequence:
    """One place a viral protein was observed, and the residues there."""

    accession: str
    taxon_name: str
    start: int
    stop: int
    sequence: str


type Row = tuple[str | int, ...]


def _write(
    path: Path, schema: Iterable[str], tables: Iterable[tuple[str, Iterable[Row]]]
) -> Path:
    """Write a vault beside where it goes, then move it there: a vault is
    replaced whole or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.unlink(missing_ok=True)
    with sqlite3.connect(partial) as connection:
        for statement in schema:
            connection.execute(statement)
        for table, rows in tables:
            rows = iter(rows)
            first = next(rows, None)
            if first is None:
                continue
            marks = ", ".join("?" * len(first))
            connection.executemany(
                f"INSERT INTO {table} VALUES ({marks})", chain([first], rows)
            )
    connection.close()
    partial.replace(path)
    return path


def write_host(directory: Path, name: str, sequences: Iterable[Row]) -> Path:
    """`sequences`: accession, sequence."""
    return _write(directory / name, HOST_SCHEMA, [("sequence", sequences)])


def write_viral(
    directory: Path,
    name: str,
    entries: Iterable[Row],
    mature: Iterable[Row],
    observations: Iterable[Row],
) -> Path:
    """`entries`: accession, taxon id, taxon name, description. `mature`:
    protein id, accession, start, stop, sequence. `observations`: description
    id, accession."""
    return _write(
        directory / name,
        VIRAL_SCHEMA,
        [("entry", entries), ("mature", mature), ("observation", observations)],
    )


def publish(written: Iterable[Path], live: Path) -> list[Path]:
    """Copy a build's vaults to where the API reads them, each replacing the
    one there whole. Called once the graph is swapped, so the vaults served
    are the live graph's."""
    live.mkdir(parents=True, exist_ok=True)
    published: list[Path] = []
    for path in written:
        partial = live / f"{path.name}.partial"
        shutil.copyfile(path, partial)
        published.append(partial.replace(live / path.name))
    return published


def _open(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is not published: build a run first")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _marks(values: Sequence[str]) -> str:
    return ", ".join("?" * len(values))


def host_sequences(
    directory: Path, taxon_id: int, accessions: Sequence[str]
) -> dict[str, str]:
    """The sequences of a host's proteins, by accession. An accession the
    host does not have is left out."""
    connection = _open(directory / host_file(taxon_id))
    try:
        found = connection.execute(
            "SELECT accession, sequence FROM sequence "
            f"WHERE accession IN ({_marks(accessions)})",
            tuple(accessions),
        ).fetchall()
    finally:
        connection.close()
    return dict(found)


def mature_sequences(directory: Path, protein_id: str) -> list[MatureSequence]:
    """Every place a viral protein was observed, with its residues there."""
    connection = _open(directory / VIRAL_FILE)
    try:
        found = connection.execute(
            """SELECT m.accession, e.taxon_name, m.start, m.stop, m.sequence
               FROM mature m JOIN entry e USING (accession)
               WHERE m.protein_id = ? ORDER BY m.accession, m.start""",
            (protein_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        MatureSequence(accession, taxon, start, stop, sequence)
        for accession, taxon, start, stop, sequence in found
    ]


def observed_entries(directory: Path, description_ids: Sequence[str]) -> dict[str, str]:
    """The viral entry each VH description observed, by description id. Any
    other description is left out."""
    connection = _open(directory / VIRAL_FILE)
    try:
        found = connection.execute(
            "SELECT description_id, accession FROM observation "
            f"WHERE description_id IN ({_marks(description_ids)})",
            tuple(description_ids),
        ).fetchall()
    finally:
        connection.close()
    return dict(found)
