"""The sequence vaults: SQLite files beside the graph, one per silo.

Sequences are kept out of the graph on purpose. Technically, so the graph stays
small enough to traverse; methodologically, so they are never the basis of
large-scale reasoning, only of the deep verification of one hypothesis. The
question a vault answers is about one protein at a time, never many.

- **A host vault**, `host-9606.sqlite`: every Swiss-Prot entry of the host, by
  accession — which is the host protein's id.
- **The viral vault**, `viral.sqlite`: every viral entry once, with its strain,
  and the mature proteins sliced from them. A viral protein (`10407:HBx`) is
  pooled over strains and entries, so it has as many sequences as places it
  was observed at. The vault also keeps which entry each VH description used,
  which the graph no longer holds.

A build writes the vaults from the same run as the graph, after the graph is
published, and replaces them whole.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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
        description TEXT NOT NULL,
        sequence    TEXT NOT NULL
    )""",
    """CREATE TABLE mature (
        protein_id TEXT NOT NULL,
        accession  TEXT NOT NULL REFERENCES entry (accession),
        start      INTEGER NOT NULL,
        stop       INTEGER NOT NULL,
        PRIMARY KEY (protein_id, accession, start, stop)
    )""",
    """CREATE TABLE observation (
        description_id TEXT PRIMARY KEY,
        accession      TEXT NOT NULL REFERENCES entry (accession)
    )""",
)
"""`sequence` is empty for an entry UniProt has retired: the strain and the
spans are still known, the residues no longer are."""


@dataclass(frozen=True, slots=True)
class ViralEntry:
    accession: str
    taxon_id: int
    taxon_name: str
    description: str
    sequence: str


@dataclass(frozen=True, slots=True)
class Mature:
    """Where one viral protein was observed: an entry, and a span of it."""

    protein_id: str
    accession: str
    start: int
    stop: int


@dataclass(frozen=True, slots=True)
class HostVault:
    taxon_id: int
    name: str
    sequences: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ViralVault:
    name: str
    entries: tuple[ViralEntry, ...]
    mature: tuple[Mature, ...]
    observations: Mapping[str, str]
    """Description id to the viral entry it observed."""


@dataclass(frozen=True, slots=True)
class MatureSequence:
    """One place a viral protein was observed, and the residues there."""

    accession: str
    taxon_name: str
    start: int
    stop: int
    sequence: str


def _create(path: Path, schema: Iterable[str]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    for statement in schema:
        connection.execute(statement)
    return connection


def write_host(directory: Path, vault: HostVault) -> Path:
    path = directory / vault.name
    with _create(path, HOST_SCHEMA) as connection:
        connection.executemany(
            "INSERT INTO sequence (accession, sequence) VALUES (?, ?)",
            sorted(vault.sequences.items()),
        )
    connection.close()
    return path


def write_viral(directory: Path, vault: ViralVault) -> Path:
    path = directory / vault.name
    with _create(path, VIRAL_SCHEMA) as connection:
        connection.executemany(
            "INSERT INTO entry VALUES (?, ?, ?, ?, ?)",
            (
                (e.accession, e.taxon_id, e.taxon_name, e.description, e.sequence)
                for e in vault.entries
            ),
        )
        connection.executemany(
            "INSERT INTO mature VALUES (?, ?, ?, ?)",
            ((m.protein_id, m.accession, m.start, m.stop) for m in vault.mature),
        )
        connection.executemany(
            "INSERT INTO observation VALUES (?, ?)", sorted(vault.observations.items())
        )
    connection.close()
    return path


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
    """Every place a viral protein was observed, sliced out of its entry. An
    entry UniProt retired gives an empty sequence."""
    connection = _open(run.vault / run.viral.vault)
    try:
        found = connection.execute(
            """SELECT m.accession, e.taxon_name, m.start, m.stop, e.sequence
               FROM mature m JOIN entry e USING (accession)
               WHERE m.protein_id = ? ORDER BY m.accession, m.start""",
            (protein_id,),
        ).fetchall()
    finally:
        connection.close()
    return [
        MatureSequence(accession, taxon, start, stop, sequence[start - 1 : stop])
        for accession, taxon, start, stop, sequence in found
    ]
