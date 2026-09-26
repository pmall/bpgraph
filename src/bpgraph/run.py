"""Where one run's files live.

A run is one directory under `data/`, named after the export it builds from —
`data/2026-09-09`. It holds three kinds of thing:

- what the relational database exported, in `export/`, exactly as produced;
- what every silo shares: the NCBI taxonomy and the two ontologies, at the top;
- one directory per silo, each holding what was fetched for it alone:
  `hosts/9606/` for human, `viral/` for our virus–host interactions.

A silo reads nothing from another. A host is its own UniProt, IntAct, GO and
PubMed; adding one adds a directory. The vaults a build writes sit in
`vault/`, one file per silo.

A new export is a new directory, so it holds nothing fetched for the last one,
and every public dump a run reads is at least as recent as its export.
"""

from dataclasses import dataclass
from pathlib import Path

HUMAN = 9606
"""The one host so far."""


@dataclass(frozen=True, slots=True)
class HostPaths:
    """One host species' silo: everything fetched for it alone."""

    taxon_id: int
    directory: Path

    @property
    def swissprot(self) -> Path:
        """Every reviewed entry of the host: names, descriptions, function
        text and the pmids it cites. Written by `bpgraph.swissprot`."""
        return self.directory / "swissprot.tsv"

    @property
    def sequences(self) -> Path:
        """The sequence of every reviewed entry, for the vault."""
        return self.directory / "sequences.tsv"

    @property
    def intact(self) -> Path:
        """IntAct's interactions of the host, filtered by `bpgraph.intact`."""
        return self.directory / "intact.tsv"

    @property
    def gaf(self) -> Path:
        """The GOA dump of the host, as downloaded."""
        return self.directory / "goa.gaf.gz"

    @property
    def go_annotations(self) -> Path:
        """Its experimental GO annotations, cut from the dump by `bpgraph.go`."""
        return self.directory / "go_annotations.tsv"

    @property
    def publications(self) -> Path:
        """PubMed metadata of every pmid the silo cites, by `bpgraph.pubmed`."""
        return self.directory / "publications.tsv"

    @property
    def vault(self) -> str:
        """The name of its sequence vault."""
        return f"host-{self.taxon_id}.sqlite"


@dataclass(frozen=True, slots=True)
class ViralPaths:
    """The viral silo: what was fetched for our virus–host interactions."""

    directory: Path

    @property
    def functions(self) -> Path:
        """UniProt function text per entry and span, by `bpgraph.uniprot`."""
        return self.directory / "functions.tsv"

    @property
    def entries(self) -> Path:
        """The sequence of every viral entry, for the vault."""
        return self.directory / "entries.tsv"

    @property
    def publications(self) -> Path:
        """PubMed metadata of every pmid the silo cites, by `bpgraph.pubmed`."""
        return self.directory / "publications.tsv"

    @property
    def vault(self) -> str:
        return "viral.sqlite"


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
        run's proteins by hand from whatever form the biologists keep them in."""
        return self.directory / "topics"

    @property
    def sources(self) -> Path:
        """Which release of each public dataset was fetched, by `bpgraph.sources`."""
        return self.directory / "sources.tsv"

    @property
    def taxdump(self) -> Path:
        """The NCBI taxonomy dump, as downloaded."""
        return self.directory / "taxdmp.zip"

    @property
    def taxonomy(self) -> Path:
        """The NCBI taxonomy dump, loaded into SQLite by `bpgraph.taxonomy`."""
        return self.directory / "taxonomy.sqlite"

    @property
    def psimi(self) -> Path:
        """The PSI-MI ontology, as downloaded by `bpgraph.psimi`."""
        return self.directory / "psi-mi.obo"

    @property
    def ontology(self) -> Path:
        """The GO ontology, as downloaded by `bpgraph.go`."""
        return self.directory / "go-basic.obo"

    @property
    def vault(self) -> Path:
        """The vaults the build writes, one SQLite file per silo."""
        return self.directory / "vault"

    def host(self, taxon_id: int = HUMAN) -> HostPaths:
        return HostPaths(taxon_id, self.directory / "hosts" / str(taxon_id))

    @property
    def viral(self) -> ViralPaths:
        return ViralPaths(self.directory / "viral")
