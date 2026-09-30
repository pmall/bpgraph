"""Our curated rows: the export's two description files, read into one file of
`Curated` records, and the viral sites they observe.

Every check a curated row can fail happens here, before anything is written:

- a `stable_id` is unique across both files;
- a row whose human partner is not a Swiss-Prot entry of the host is dropped,
  and the accessions are logged;
- every viral taxon has a curated virus, or the build fails naming the taxa;
- every viral partner is a row of `viral_proteins.tsv`, under the same name
  and taxon, whose sequence goes to the vault.

A dropped row stays in the file, marked, because its peptides are still its
own: they are dropped with it rather than orphaned.
"""

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.ids import viral_protein_id
from bpgraph.loaders.export import ExportRow, export_rows, viral_proteins
from bpgraph.loaders.records import ABSENT, KEPT, Curated, Site, of
from bpgraph.loaders.tsv import LoadError
from bpgraph.psimi import Ontology
from bpgraph.taxonomy import TaxonomyUnavailable
from bpgraph.viruses import CuratedViruses, UncuratedTaxa

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CuratedFiles:
    curated: Path
    """Every curated row, unsorted."""
    sites: Path
    """The viral sites kept rows observe, unsorted."""
    exported: Path
    """Every row of `viral_proteins.tsv`, sorted by site."""


def _curated(row: ExportRow) -> Curated:
    second = row.second
    return Curated(
        stable_id=row.stable_id,
        kind=row.kind.value,
        status=KEPT,
        pmid=row.pmid,
        psimi_id=row.psimi_id,
        accession_1=row.first.accession,
        accession_2=second.accession,
        start_2=str(second.start),
        stop_2=str(second.stop),
        name_2=second.name,
        taxon_2=str(second.taxon_id),
        partner_2=second.accession if row.kind is InteractionKind.HH else "",
        strain_id="",
        strain_name="",
        path=str(row.cursor.path),
        line=str(row.cursor.line),
    )


def _read(
    run_export: Path,
    ontology: Ontology,
    ids: TextIO,
) -> Iterator[list[str]]:
    """Every row, keyed by its first partner's accession."""
    for row in export_rows(run_export, ontology):
        ids.write(f"{row.stable_id}\t{row.cursor.path}\t{row.cursor.line}\n")
        curated = _curated(row)
        yield [curated.accession_1, *curated]


def _unique(ids: Path) -> None:
    """Fail on the first `stable_id` two rows share."""
    for (stable_id,), found in files.groups(files.read(files.sort(ids)), 1):
        if len(found) > 1:
            _, path, line = found[1]
            raise LoadError(
                f"{Path(path).name}:{line}: stable_id {stable_id!r} appears twice"
            )


def _on_swissprot(keyed: Path, proteins: Path, absent: TextIO) -> Iterator[Curated]:
    """The rows of a file keyed by a human accession, marked `absent` when
    Swiss-Prot has no such entry."""
    for (accession,), found, entry in files.cogroup(
        files.read(keyed), files.read(proteins), 1
    ):
        for record in found:
            curated = of(Curated, record, 1)
            if not entry and curated.status == KEPT:
                absent.write(accession + "\n")
                curated = curated.with_status(ABSENT)
            yield curated


def _placed(
    by_taxon: Path, viruses: CuratedViruses, uncurated: set[int]
) -> Iterator[list[str]]:
    """VH rows with their viral partner placed, keyed by its site. The taxon is
    resolved once per taxon the export names."""
    taxonomy = viruses.taxonomy
    for (taxon,), found in files.groups(files.read(by_taxon), 1):
        rows = [of(Curated, record, 1) for record in found]
        try:
            strain = taxonomy.canonical(int(taxon))
        except TaxonomyUnavailable as error:
            raise rows[0].cursor.fail(str(error)) from None
        virus = viruses.enclosing(strain)
        if virus is None and any(r.status == KEPT for r in rows):
            uncurated.add(strain)
        name = taxonomy.name(strain)
        for curated in rows:
            placed = curated._replace(
                partner_2=viral_protein_id(virus.taxon_id, curated.name_2)
                if virus
                else "",
                strain_id=str(strain),
                strain_name=name,
            )
            yield [*placed.site_2, *placed]


def _viral_sites(
    by_site: Path, export: Path, scratch: Path, out: TextIO, sites: TextIO
) -> Path:
    """Match each VH row's viral partner with its row of `viral_proteins.tsv`,
    and write the sites kept rows observe. Returns `viral_proteins.tsv` sorted
    by site."""
    known = files.sorted_file(
        scratch / "viral_proteins",
        (
            [
                p.accession,
                str(p.start),
                str(p.stop),
                p.name,
                str(p.taxon_id),
                p.sequence,
            ]
            for p in viral_proteins(export)
        ),
    )
    for site, found, protein in files.cogroup(
        files.read(by_site), files.read(known), 3
    ):
        rows = [of(Curated, record, 3) for record in found]
        if not rows:
            continue
        if not protein:
            raise rows[0].cursor.fail(f"{':'.join(site)} is not in viral_proteins.tsv")
        _, _, _, name, taxon, sequence = protein[0]
        for curated in rows:
            if (curated.name_2, curated.taxon_2) != (name, taxon):
                raise curated.cursor.fail(
                    f"{':'.join(site)} is {curated.name_2} of taxon {curated.taxon_2} "
                    f"here and {name} of taxon {taxon} in viral_proteins.tsv"
                )
            out.write("\t".join(curated) + "\n")
        kept = next((r for r in rows if r.status == KEPT), None)
        if kept is not None:
            virus_id = kept.partner_2.partition(":")[0]
            record = Site(
                kept.partner_2,
                virus_id,
                kept.name_2,
                site[0],
                site[1],
                site[2],
                kept.strain_id,
                kept.strain_name,
                sequence,
            )
            sites.write("\t".join(record) + "\n")
    return known


def load_curated(
    export: Path,
    proteins: Path,
    scratch: Path,
    ontology: Ontology,
    viruses: CuratedViruses,
) -> CuratedFiles:
    """Read the export's description files."""
    ids = scratch / "stable_ids"
    with ids.open("w", encoding="utf-8") as handle:
        by_first = files.sorted_file(
            scratch / "by_first",
            _read(export, ontology, handle),
        )
    _unique(ids)

    curated, sites = scratch / "curated", scratch / "sites"
    absent = scratch / "absent"
    with (
        absent.open("w", encoding="utf-8") as lacking,
        curated.open("w", encoding="utf-8") as out,
    ):
        by_second = scratch / "by_second"
        by_taxon = scratch / "by_taxon"
        with (
            by_second.open("w", encoding="utf-8") as hh,
            by_taxon.open("w", encoding="utf-8") as vh,
        ):
            for row in _on_swissprot(by_first, proteins, lacking):
                if row.kind == InteractionKind.HH.value:
                    hh.write("\t".join([row.accession_2, *row]) + "\n")
                else:
                    vh.write("\t".join([row.taxon_2, *row]) + "\n")
        for row in _on_swissprot(files.sort(by_second), proteins, lacking):
            out.write("\t".join(row) + "\n")

        uncurated_taxa: set[int] = set()
        by_site = files.sorted_file(
            scratch / "by_site", _placed(files.sort(by_taxon), viruses, uncurated_taxa)
        )
        if uncurated_taxa:
            named = ", ".join(
                f"{t} {viruses.taxonomy.name(t)!r}" for t in sorted(uncurated_taxa)
            )
            raise UncuratedTaxa(
                f"{len(uncurated_taxa)} viral taxa have no curated virus in "
                f"viruses.tsv: {named}"
            )
        with sites.open("w", encoding="utf-8") as observed:
            exported = _viral_sites(by_site, export, scratch, out, observed)

    statuses = Counter(of(Curated, record).status for record in files.read(curated))
    if statuses[ABSENT]:
        accessions = [r[0] for r in files.read(files.sort(absent, unique=True))]
        logger.warning(
            "dropped %d curated rows whose human partner is not in Swiss-Prot: %s",
            statuses[ABSENT],
            ", ".join(accessions),
        )
    return CuratedFiles(curated, sites, exported)
