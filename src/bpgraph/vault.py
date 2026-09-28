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

A build writes the vaults from the same run as the graph, after the graph is
published, and replaces them whole.
"""

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import chain
from pathlib import Path

from bpgraph.run import Run

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


def _open(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"{path} does not exist: build the run first")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def host_sequence(run: Run, accession: str, taxon_id: int) -> str | None:
    """A host protein's sequence, or nothing if the host has no such entry."""
    host = run.host(taxon_id)
    connection = _open(run.vault / host.vault)
    try:
        row = connection.execute(
            "SELECT sequence FROM sequence WHERE accession = ?", (accession,)
        ).fetchone()
    finally:
        connection.close()
    return None if row is None else row[0]


def mature_sequences(run: Run, protein_id: str) -> list[MatureSequence]:
    """Every place a viral protein was observed, with its residues there."""
    connection = _open(run.vault / run.viral.vault)
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
