"""Preparing a run: every file a build writes from, checked, in `build/`.

Nothing is written to the graph until this is done, so every error a run can
hold — a malformed row, a viral taxon nobody curated, a peptide on
no row, a cited pmid with no metadata — fails here, with the file and line.

What the silos share is joined here, and nowhere else:

- **Methods.** A method is named from PSI-MI, not from whatever copy of the
  name a source carries.
- **Publications.** A pmid two silos cite is one publication, taken from the
  first silo that has it. Only pmids something cites are kept.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from bpgraph import files
from bpgraph.loaders.curated import load_curated
from bpgraph.loaders.host import hh_descriptions
from bpgraph.loaders.peptides import reports
from bpgraph.loaders.records import Description, ViralProtein, of
from bpgraph.loaders.tsv import LoadError, listed, rows
from bpgraph.loaders.viral import vh_descriptions, viral_proteins
from bpgraph.psimi import read_ontology
from bpgraph.pubmed import COLUMNS as PUBLICATION_COLUMNS
from bpgraph.run import HUMAN, HostPaths, Run
from bpgraph.taxonomy import Taxon, Taxonomy
from bpgraph.viruses import CuratedViruses, Virus

logger = logging.getLogger(__name__)

MISSING_REPORTED = 5


@dataclass(frozen=True, slots=True)
class Prepared:
    """Everything a build writes, as files in the run's `build/`."""

    host: HostPaths
    descriptions: Path
    """`Description` records, sorted by interaction."""
    reports: Path
    """`Report` records, sorted by interaction."""
    viral_proteins: Path
    """`ViralProtein` records."""
    viruses: tuple[Virus, ...]
    families: tuple[tuple[int, Taxon], ...]
    """Each virus with a family, and that family."""
    publications: Path
    """Every publication something cites, in `publications.tsv` order."""
    sites: Path
    """`Site` records: the vault's mature proteins."""
    entries: Path
    """The vault's viral entries."""
    observations: Path
    """The vault's observations: description id, viral entry."""


def _cited(host: HostPaths, descriptions: Path, proteins: Path) -> Iterator[list[str]]:
    """Every pmid the graph cites: descriptions, GO annotations, and the
    function text of every protein."""
    for record in files.read(descriptions):
        yield [of(Description, record).pmid]
    for _, row in rows(host.go_annotations):
        yield [row["pmid"]]
    for cursor, row in rows(host.swissprot):
        yield from ([pmid] for pmid in listed(cursor, row, "pmids"))
    for record in files.read(proteins):
        yield from (
            [pmid] for pmid in of(ViralProtein, record).pmids.split(";") if pmid
        )


def _publications(run: Run, host: HostPaths, cited: Path, scratch: Path) -> Path:
    """The cited publications, from the first silo that has each. A cited pmid
    no silo has fails the build: its silo's publications are not fetched."""
    fetched = files.sorted_file(
        scratch / "fetched",
        (
            [row["pmid"], rank, *(row[c] for c in PUBLICATION_COLUMNS[1:])]
            for rank, path in (("0", host.publications), ("1", run.viral.publications))
            for _, row in rows(path)
        ),
    )
    publications = scratch / "publications"
    missing: list[str] = []
    count = 0
    with publications.open("w", encoding="utf-8") as out:
        for (pmid,), wanted, found in files.cogroup(
            files.read(cited), files.read(fetched), 1
        ):
            if not wanted:
                continue
            if not found:
                count += 1
                if len(missing) < MISSING_REPORTED:
                    missing.append(pmid)
                continue
            out.write("\t".join([pmid, *found[0][2:]]) + "\n")
    if count:
        raise LoadError(
            f"{count} cited pmids have no metadata, e.g. {', '.join(missing)}: "
            f"run bpgraph-pubmed {run.directory}"
        )
    return publications


def prepare(run: Run, scratch: Path) -> Prepared:
    """Read and check every silo of a run into `scratch`."""
    psimi = read_ontology(run.psimi)

    @cache
    def name_of(psimi_id: str) -> str:
        return psimi.terms[psimi_id].name

    taxonomy = Taxonomy.open(run.taxonomy)
    viruses = CuratedViruses.load(taxonomy)
    host = run.host(HUMAN)

    proteins = files.sorted_file(
        scratch / "swissprot", ([row["accession"]] for _, row in rows(host.swissprot))
    )
    curated = load_curated(run.export, proteins, scratch, psimi, viruses)

    descriptions = scratch / "descriptions"
    observations = scratch / "observations"
    with (
        descriptions.open("w", encoding="utf-8") as out,
        observations.open("w", encoding="utf-8") as observed,
    ):
        hh_descriptions(host, curated.curated, scratch, name_of, out)
        vh_descriptions(curated.curated, name_of, out, observed)
    files.sort(descriptions)

    viral = viral_proteins(run.viral, curated.sites, curated.exported, scratch)
    virus_ids = files.sorted_file(
        scratch / "viruses",
        ([of(ViralProtein, r).virus_id] for r in files.read(viral.proteins)),
        unique=True,
    )
    used = tuple(viruses.viruses[int(v)] for (v,) in files.read(virus_ids))

    cited = files.sorted_file(
        scratch / "cited", _cited(host, descriptions, viral.proteins), unique=True
    )
    return Prepared(
        host=host,
        descriptions=descriptions,
        reports=reports(run.export, curated.curated, descriptions, scratch),
        viral_proteins=viral.proteins,
        viruses=used,
        families=tuple(taxonomy.families(v.taxon_id for v in used)),
        publications=_publications(run, host, cited, scratch),
        sites=curated.sites,
        entries=viral.entries,
        observations=observations,
    )
