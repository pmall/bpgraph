"""Where one run's files live.

A run is one directory under `data/`, named after the export it builds from —
`data/2026-09-09`. What the relational database exported sits in its `export/`
subdirectory exactly as produced; everything this repo fetches or derives for
that export sits beside it, under a fixed name. A new export is a new
directory, so it holds nothing fetched for the last one, and every public dump
a run reads is at least as recent as its export.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GoPaths:
    """The three GO files fetched for one export, which stand or fall together.

    They are written by one command and read by one loader: terms the edges
    join, and annotations pointing at those terms. Holding them as a trio is
    what lets a half-deleted set be caught as such.
    """

    terms: Path
    edges: Path
    annotations: Path

    @property
    def paths(self) -> tuple[Path, ...]:
        return (self.terms, self.edges, self.annotations)

    @property
    def missing(self) -> tuple[Path, ...]:
        return tuple(path for path in self.paths if not path.exists())


@dataclass(frozen=True, slots=True)
class Run:
    """One run directory, and the name of every file in it."""

    directory: Path

    @property
    def export(self) -> Path:
        """What the relational database exported, and nothing else."""
        return self.directory / "export"

    @property
    def topics(self) -> Path:
        """The curated topic lists, one TSV per topic, resolved against this
        export by hand from whatever form the biologists keep them in."""
        return self.directory / "topics"

    @property
    def sources(self) -> Path:
        """Which release of each public dataset was fetched, by `bpgraph.sources`."""
        return self.directory / "sources.tsv"

    @property
    def functions(self) -> Path:
        """The UniProt function text, written by `bpgraph.uniprot`."""
        return self.directory / "functions.tsv"

    @property
    def go(self) -> GoPaths:
        """The GO trio, written by `bpgraph.go`."""
        return GoPaths(
            terms=self.directory / "go_terms.tsv",
            edges=self.directory / "go_edges.tsv",
            annotations=self.directory / "go_annotations.tsv",
        )

    @property
    def ontology(self) -> Path:
        """The GO ontology dump the trio is cut from."""
        return self.directory / "go-basic.obo"

    @property
    def annotations(self) -> Path:
        """The GOA human dump the trio is cut from."""
        return self.directory / "goa_human.gaf.gz"

    @property
    def taxdump(self) -> Path:
        """The NCBI taxonomy dump, as downloaded."""
        return self.directory / "taxdmp.zip"

    @property
    def taxonomy(self) -> Path:
        """The NCBI taxonomy dump, loaded into SQLite by `bpgraph.taxonomy`."""
        return self.directory / "taxonomy.sqlite"
