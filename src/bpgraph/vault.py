"""The sequence vaults: SQLite files beside the graph, one per silo.

Sequences are kept out of the graph on purpose. Technically, so the graph stays
small enough to traverse; methodologically, so they are never the basis of
large-scale reasoning, only of the deep verification of one hypothesis. The
question a vault answers is about one protein at a time, never many.

- **A host vault**, `host-9606.sqlite`: every Swiss-Prot entry of the host, by
  accession, the human protein's key.
- **The viral vault**, `viral.sqlite`: every viral entry once, with its strain,
  and the mature proteins observed on them, each with the sequence curation
  recorded. A viral protein (`HBx` of HBV, 10407) is pooled over strains and entries,
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
        ncbi_taxon_id INTEGER NOT NULL,
        name          TEXT NOT NULL,
        accession     TEXT NOT NULL REFERENCES entry (accession),
        start         INTEGER NOT NULL,
        stop          INTEGER NOT NULL,
        sequence      TEXT NOT NULL,
        PRIMARY KEY (ncbi_taxon_id, name, accession, start, stop)
    )""",
    """CREATE TABLE observation (
        stable_id TEXT PRIMARY KEY,
        accession TEXT NOT NULL REFERENCES entry (accession)
    )""",
)
"""An entry's `taxon_id` and `taxon_name` are its strain's; `description` is
UniProt's protein name, empty for an entry UniProt has retired. A mature
protein is keyed as the graph keys a viral protein, by its virus's NCBI taxon
id and its name; an observation by the stable id of the curated description
that made it."""


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
    NCBI taxon id, name, accession, start, stop, sequence. `observations`:
    stable id, accession."""
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


def mature_sequences(
    directory: Path, ncbi_taxon_id: int, name: str
) -> list[MatureSequence]:
    """Every place a viral protein was observed, with its residues there."""
    connection = _open(directory / VIRAL_FILE)
    try:
        found = connection.execute(
            """SELECT m.accession, e.taxon_name, m.start, m.stop, m.sequence
               FROM mature m JOIN entry e USING (accession)
               WHERE m.ncbi_taxon_id = ? AND m.name = ?
               ORDER BY m.accession, m.start""",
            (ncbi_taxon_id, name),
        ).fetchall()
    finally:
        connection.close()
    return [
        MatureSequence(accession, taxon, start, stop, sequence)
        for accession, taxon, start, stop, sequence in found
    ]


def observed_sequences(
    directory: Path, observed: dict[str, tuple[int, str]]
) -> dict[str, MatureSequence]:
    """The mature protein each VH description observed, by stable id:
    `observed` maps a description to its viral protein's taxon id and name,
    and the entry the description observed holds that protein once."""
    connection = _open(directory / VIRAL_FILE)
    try:
        found = {
            stable_id: MatureSequence(*row)
            for stable_id, (ncbi_taxon_id, name) in observed.items()
            for row in connection.execute(
                """SELECT m.accession, e.taxon_name, m.start, m.stop, m.sequence
                   FROM observation o
                   JOIN mature m ON m.accession = o.accession
                   JOIN entry e ON e.accession = m.accession
                   WHERE o.stable_id = ? AND m.ncbi_taxon_id = ? AND m.name = ?""",
                (stable_id, ncbi_taxon_id, name),
            )
        }
    finally:
        connection.close()
    return found
