"""The NCBI taxonomy, kept in SQLite in the run directory.

The graph holds only the taxa an analysis groups by — the curated viruses of
`bpgraph.viruses`, and the family above each. Placing a strain under its virus
and a virus under its family needs the whole tree, three million rows that have
no business in the graph.

Each taxon keeps its parent, as the dump gives it, and is loaded row by row. A
taxon's ancestors are a walk up its parents, one indexed lookup per level, and
the tree is some forty levels deep at most.
"""

import sqlite3
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj
from typing import Self
from urllib.request import urlopen

from bpgraph.run import Run
from bpgraph.sources import record_source

TAXDUMP_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdmp.zip"

SCIENTIFIC_NAME = "scientific name"
FAMILY = "family"
MERGE_DEPTH = 8

SCHEMA = (
    """
    CREATE TABLE taxon (
        tax_id    INTEGER PRIMARY KEY,
        parent_id INTEGER NOT NULL,
        rank      TEXT    NOT NULL,
        name      TEXT    NOT NULL
    )
    """,
    "CREATE TABLE merged (old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL)",
)

ANCESTORS = """WITH RECURSIVE up (tax_id, depth) AS (
    SELECT ?, 0
    UNION ALL
    SELECT t.parent_id, up.depth + 1 FROM taxon t JOIN up USING (tax_id)
    WHERE t.parent_id <> t.tax_id
)
SELECT t.tax_id, t.rank, t.name FROM up JOIN taxon t USING (tax_id)
ORDER BY up.depth"""
"""A taxon, then each taxon above it, nearest first. The root is its own
parent, which is where the walk stops."""


class TaxonomyUnavailable(RuntimeError):
    """The local taxonomy is missing, or does not hold a taxon."""


@dataclass(frozen=True, slots=True)
class Taxon:
    taxon_id: int
    rank: str
    name: str


def _fields(line: bytes) -> list[str]:
    """One dump row. NCBI separates fields with `\\t|\\t` and ends with `\\t|`."""
    return line.decode("utf-8").rstrip("\n").removesuffix("\t|").split("\t|\t")


def load_taxdump(taxdump: Path, database: Path) -> int:
    """Copy the dump into SQLite, row by row. Returns the taxa count."""
    database.parent.mkdir(parents=True, exist_ok=True)
    database.unlink(missing_ok=True)
    with zipfile.ZipFile(taxdump) as archive, sqlite3.connect(database) as connection:
        for statement in SCHEMA:
            connection.execute(statement)
        with archive.open("nodes.dmp") as handle:
            connection.executemany(
                "INSERT INTO taxon VALUES (?, ?, ?, '')",
                ((int(f[0]), int(f[1]), f[2]) for f in map(_fields, handle)),
            )
        with archive.open("names.dmp") as handle:
            connection.executemany(
                "UPDATE taxon SET name = ? WHERE tax_id = ?",
                (
                    (f[1], int(f[0]))
                    for f in map(_fields, handle)
                    if f[3] == SCIENTIFIC_NAME
                ),
            )
        with archive.open("merged.dmp") as handle:
            connection.executemany(
                "INSERT INTO merged VALUES (?, ?)",
                ((int(f[0]), int(f[1])) for f in map(_fields, handle)),
            )
        (count,) = connection.execute("SELECT count(*) FROM taxon").fetchone()
    connection.close()
    return count


def fetch(run: Run) -> tuple[int, str]:
    """Download the dump, load it, and delete it: the database is what a run
    keeps. Returns the taxa count and the dump's `Last-Modified`, which stands
    in for the release NCBI does not name."""
    with tempfile.TemporaryDirectory(dir=run.directory) as scratch:
        dump = Path(scratch) / "taxdmp.zip"
        with urlopen(TAXDUMP_URL) as response, dump.open("wb") as handle:
            copyfileobj(response, handle)
            release = response.headers.get("Last-Modified", "")
        return load_taxdump(dump, run.taxonomy), release


@dataclass(frozen=True, slots=True)
class Taxonomy:
    """Read access to the local taxonomy."""

    connection: sqlite3.Connection

    @classmethod
    def open(cls, database: Path) -> Self:
        if not database.exists():
            raise TaxonomyUnavailable(
                f"{database} does not exist: run bpgraph-taxonomy"
            )
        return cls(sqlite3.connect(f"file:{database}?mode=ro", uri=True))

    def canonical(self, tax_id: int) -> int:
        """Follow NCBI's merges to the id a taxon now has."""
        current = tax_id
        for _ in range(MERGE_DEPTH):
            if self.connection.execute(
                "SELECT 1 FROM taxon WHERE tax_id = ?", (current,)
            ).fetchone():
                return current
            row = self.connection.execute(
                "SELECT new_id FROM merged WHERE old_id = ?", (current,)
            ).fetchone()
            if row is None:
                raise TaxonomyUnavailable(
                    f"taxon {tax_id} is neither current nor merged"
                )
            current = row[0]
        raise TaxonomyUnavailable(f"taxon {tax_id} merges in a cycle")

    def name(self, tax_id: int) -> str:
        row = self.connection.execute(
            "SELECT name FROM taxon WHERE tax_id = ?", (tax_id,)
        ).fetchone()
        if row is None:
            raise TaxonomyUnavailable(f"taxon {tax_id} is not in the taxonomy")
        return row[0]

    def lineage(self, tax_id: int) -> Iterator[Taxon]:
        """The taxon, then everything above it, nearest first."""
        for taxon_id, rank, name in self.connection.execute(ANCESTORS, (tax_id,)):
            yield Taxon(taxon_id, rank, name)

    def family(self, tax_id: int) -> Taxon | None:
        """The family above a taxon, if it has one."""
        return next((t for t in self.lineage(tax_id) if t.rank == FAMILY), None)

    def families(self, virus_ids: Iterable[int]) -> Iterator[tuple[int, Taxon]]:
        """Each virus with the family above it. A virus with no family is left
        out: it stays queryable, it just falls out of family rollups."""
        for virus_id in virus_ids:
            family = self.family(virus_id)
            if family is not None:
                yield virus_id, family


def main() -> None:
    """Fetch the taxonomy into one run directory.

    `uv run bpgraph-taxonomy data/2026-09-09` writes `taxonomy.sqlite` beside
    the export, and records the fetch.
    """
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-taxonomy <run directory>")
    run = Run(Path(sys.argv[1]))
    count, release = fetch(run)
    record_source(run.sources, "taxonomy", TAXDUMP_URL, release)
    print(f"{run.taxonomy}: {count} taxa, released {release}")
