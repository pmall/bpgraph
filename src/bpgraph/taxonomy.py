"""The NCBI taxonomy, kept in SQLite in the run directory.

The graph holds only the taxa an analysis groups by — the curated viruses of
`bpgraph.viruses`, and the family above each. Placing a strain under its virus
and a virus under its family needs the whole tree, three million rows that have
no business in the graph.

The dump gives parent links, which would make every ancestor lookup a walk. So
the load numbers the tree as a nested set: a taxon's descendants are exactly
the rows whose interval sits inside its own, and its ancestors exactly those
whose interval contains it. Both are then one indexed range query.
"""

import sqlite3
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj
from typing import Self
from urllib.request import urlopen

from bpgraph.models import Family, TaxonLink
from bpgraph.run import Run
from bpgraph.sources import record_source

TAXDUMP_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdmp.zip"

SCIENTIFIC_NAME = "scientific name"
GROUPING_RANKS = ("family",)
ROOT = 1
MERGE_DEPTH = 8

SCHEMA = (
    """
    CREATE TABLE taxon (
        tax_id INTEGER PRIMARY KEY,
        rank   TEXT    NOT NULL,
        name   TEXT    NOT NULL,
        lft    INTEGER NOT NULL,
        rgt    INTEGER NOT NULL
    )
    """,
    "CREATE TABLE merged (old_id INTEGER PRIMARY KEY, new_id INTEGER NOT NULL)",
    "CREATE INDEX taxon_rank_interval ON taxon (rank, lft, rgt)",
)
"""Rank leads the index: an interval is two open-ended comparisons, which no
B-tree seeks well on its own. Seeking the rank first leaves a few thousand rows
to scan instead of three million, and the index covers the query outright."""


class TaxonomyUnavailable(RuntimeError):
    """The local taxonomy is missing, or does not hold a taxon."""


def _fields(line: bytes) -> list[str]:
    """One dump row. NCBI separates fields with `\\t|\\t` and ends with `\\t|`."""
    return line.decode("utf-8").rstrip("\n").removesuffix("\t|").split("\t|\t")


def download_taxdump(destination: Path) -> str:
    """Fetch the current dump from NCBI. It is reissued regularly, and names
    no release of its own, so its `Last-Modified` stands in for one."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(TAXDUMP_URL) as response, destination.open("wb") as handle:
        copyfileobj(response, handle)
        return response.headers.get("Last-Modified", "")


def _nested_set(children: dict[int, list[int]]) -> dict[int, tuple[int, int]]:
    """Number the tree depth-first, iteratively — it is three million deep-ish."""
    bounds: dict[int, tuple[int, int]] = {}
    opened: dict[int, int] = {}
    counter = 1
    stack: list[tuple[int, bool]] = [(ROOT, False)]
    while stack:
        node, closing = stack.pop()
        if closing:
            bounds[node] = (opened[node], counter)
        else:
            opened[node] = counter
            stack.append((node, True))
            stack.extend((child, False) for child in children.get(node, ()))
        counter += 1
    return bounds


def load_taxdump(taxdump: Path, database: Path) -> int:
    """Copy the dump into SQLite, numbered as a nested set. Returns the taxa count."""
    ranks: dict[int, str] = {}
    children: dict[int, list[int]] = {}
    with zipfile.ZipFile(taxdump) as archive:
        with archive.open("nodes.dmp") as handle:
            for line in handle:
                tax_id, parent_id, rank = _fields(line)[:3]
                node, parent = int(tax_id), int(parent_id)
                ranks[node] = rank
                if node != parent:
                    children.setdefault(parent, []).append(node)

        bounds = _nested_set(children)
        missing = len(ranks) - len(bounds)
        if missing:
            raise TaxonomyUnavailable(f"{missing} taxa are not reachable from the root")

        database.parent.mkdir(parents=True, exist_ok=True)
        database.unlink(missing_ok=True)
        with sqlite3.connect(database) as connection:
            for statement in SCHEMA:
                connection.execute(statement)
            connection.executemany(
                "INSERT INTO taxon (tax_id, rank, name, lft, rgt)"
                " VALUES (?, ?, '', ?, ?)",
                ((node, rank, *bounds[node]) for node, rank in ranks.items()),
            )
            with archive.open("names.dmp") as handle:
                connection.executemany(
                    "UPDATE taxon SET name = ? WHERE tax_id = ?",
                    (
                        (fields[1], int(fields[0]))
                        for fields in map(_fields, handle)
                        if fields[3] == SCIENTIFIC_NAME
                    ),
                )
            with archive.open("merged.dmp") as handle:
                connection.executemany(
                    "INSERT INTO merged (old_id, new_id) VALUES (?, ?)",
                    ((int(f[0]), int(f[1])) for f in map(_fields, handle)),
                )
    return len(ranks)


@dataclass(frozen=True, slots=True)
class Taxonomy:
    """Read access to the local taxonomy."""

    connection: sqlite3.Connection

    @classmethod
    def open(cls, database: Path) -> Self:
        if not database.exists():
            raise TaxonomyUnavailable(
                f"{database} does not exist. Fetch the dump beside it with "
                "bpgraph.taxonomy.download_taxdump() and build it with load_taxdump()"
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

    def interval(self, tax_id: int) -> tuple[int, int]:
        """A taxon's nested-set bounds: its descendants sit inside them."""
        row = self.connection.execute(
            "SELECT lft, rgt FROM taxon WHERE tax_id = ?", (tax_id,)
        ).fetchone()
        if row is None:
            raise TaxonomyUnavailable(f"taxon {tax_id} is not in the taxonomy")
        return row[0], row[1]

    def name(self, tax_id: int) -> str:
        row = self.connection.execute(
            "SELECT name FROM taxon WHERE tax_id = ?", (tax_id,)
        ).fetchone()
        if row is None:
            raise TaxonomyUnavailable(f"taxon {tax_id} is not in the taxonomy")
        return row[0]

    def ancestors(
        self, tax_id: int, ranks: Iterable[str] = GROUPING_RANKS
    ) -> list[Family]:
        """Enclosing taxa at the given ranks, nearest first. One range query."""
        wanted = tuple(ranks)
        rows = self.connection.execute(
            f"""SELECT t.tax_id, t.name FROM taxon t, taxon self
                WHERE self.tax_id = ?
                  AND t.lft < self.lft AND t.rgt > self.rgt
                  AND t.rank IN ({",".join("?" * len(wanted))})
                ORDER BY t.lft DESC""",
            (tax_id, *wanted),
        ).fetchall()
        return [Family(taxon_id=r[0], name=r[1]) for r in rows]

    def families(
        self, virus_ids: Iterable[int]
    ) -> tuple[tuple[Family, ...], tuple[TaxonLink, ...]]:
        """The family above each virus, and the `:PARENT` edge to it.

        A virus with no family gets no edge: it stays queryable, it just falls
        out of family rollups.
        """
        families: dict[int, Family] = {}
        links: list[TaxonLink] = []
        for virus_id in sorted(set(virus_ids)):
            above = self.ancestors(virus_id)
            if not above:
                continue
            family = above[0]
            families.setdefault(family.taxon_id, family)
            links.append(
                TaxonLink(child_taxon_id=virus_id, parent_taxon_id=family.taxon_id)
            )
        return tuple(families.values()), tuple(links)


def main() -> None:
    """Fetch the taxonomy into one run directory and load it into SQLite.

    `uv run bpgraph-taxonomy data/2026-09-09` writes `taxdmp.zip` and
    `taxonomy.sqlite` beside the export, and records the fetch.
    """
    import sys

    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-taxonomy <run directory>")
    run = Run(Path(sys.argv[1]))
    release = download_taxdump(run.taxdump)
    record_source(run.sources, "taxonomy", TAXDUMP_URL, release)
    count = load_taxdump(run.taxdump, run.taxonomy)
    print(f"{run.taxonomy}: {count} taxa, released {release}")
