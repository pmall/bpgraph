"""Our curated rows: the export's two description files, read into one file of
`Curated` records, the viral sites they observe, and the viruses they name.

Every check a curated row can fail happens here, before anything is written:

- a `stable_id` is unique across both files;
- every human partner is a row of `interactors_human`, a protein of the host;
- every viral partner is a row of `interactors_viral`, whose name and sequence
  go to the vault, and the rows observing one site agree on its protein, virus,
  strain and release;
- a virus has one name.

Curation groups the viral proteins, as `bpgraph.loaders.export` says, and the
grouping is taken as given.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.loaders.export import ExportRow, export_rows, viral_sites
from bpgraph.loaders.records import Curated, Site, of, viral_ref
from bpgraph.loaders.tsv import LoadError
from bpgraph.psimi import Ontology


@dataclass(frozen=True, slots=True)
class CuratedFiles:
    curated: Path
    """Every curated row, unsorted."""
    sites: Path
    """The viral sites VH rows observe, unsorted."""
    exported: Path
    """Every row of `interactors_viral`, sorted by site."""
    viruses: Path
    """The viruses VH rows name: taxon id, name, sorted."""


def _curated(row: ExportRow) -> Curated:
    viral = row.viral
    return Curated(
        stable_id=row.stable_id,
        kind=row.kind.value,
        pmid=row.pmid,
        psimi_id=row.psimi_id,
        accession_1=row.first,
        accession_2=row.second,
        start_2=str(viral.start) if viral else "",
        stop_2=str(viral.stop) if viral else "",
        name_2=viral.name if viral else "",
        virus_id=str(viral.virus_id) if viral else "",
        virus_name=viral.virus_name if viral else "",
        strain_id=str(viral.strain_id) if viral else "",
        strain_name=viral.strain_name if viral else "",
        release_2=viral.release if viral else "",
        partner_2=viral_ref(viral.virus_id, viral.name) if viral else row.second,
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


def _on_host(keyed: Path, proteins: Path) -> Iterator[Curated]:
    """The rows of a file keyed by a human accession, which must be a protein
    of the host."""
    for (accession,), found, entry in files.cogroup(
        files.read(keyed), files.read(proteins), 1
    ):
        rows = [of(Curated, record, 1) for record in found]
        if rows and not entry:
            raise rows[0].cursor.fail(f"{accession} is not in interactors_human")
        yield from rows


def _placement(row: Curated) -> tuple[str, str, str, str, str]:
    """What every row observing one site must agree on."""
    return (row.name_2, row.virus_id, row.strain_id, row.strain_name, row.release_2)


def _viral_sites(
    by_site: Path, export: Path, scratch: Path, out: TextIO, sites: TextIO
) -> Path:
    """Match each VH row's viral partner with its row of `interactors_viral`,
    and write the sites they observe. Returns `interactors_viral` sorted
    by site."""
    known = files.sorted_file(
        scratch / "viral_sites",
        (
            [
                s.accession,
                str(s.start),
                str(s.stop),
                s.release,
                s.description,
                s.sequence,
            ]
            for s in viral_sites(export)
        ),
    )
    for site, found, exported in files.cogroup(
        files.read(by_site), files.read(known), 3
    ):
        rows = [of(Curated, record, 3) for record in found]
        if not rows:
            continue
        where = ":".join(site)
        if not exported:
            raise rows[0].cursor.fail(f"{where} is not in interactors_viral")
        _, _, _, release, description, sequence = exported[0]
        first = rows[0]
        for curated in rows:
            if _placement(curated) != _placement(first):
                raise curated.cursor.fail(
                    f"{where} is {curated.name_2} of taxon {curated.virus_id} here "
                    f"and {first.name_2} of taxon {first.virus_id} at line {first.line}"
                )
            if curated.release_2 != release:
                raise curated.cursor.fail(
                    f"{where} is of release {curated.release_2} here and "
                    f"{release} in interactors_viral"
                )
            out.write("\t".join(curated) + "\n")
        record = Site(
            first.partner_2,
            first.virus_id,
            first.name_2,
            site[0],
            site[1],
            site[2],
            first.strain_id,
            first.strain_name,
            release,
            description,
            sequence,
        )
        sites.write("\t".join(record) + "\n")
    return known


def _viruses(curated: Path, scratch: Path) -> Path:
    """The viruses VH rows name, each once. A taxon under two names
    fails."""
    named = files.sorted_file(
        scratch / "viruses",
        (
            [row.virus_id, row.virus_name]
            for row in (of(Curated, record) for record in files.read(curated))
            if row.kind == InteractionKind.VH.value
        ),
        unique=True,
    )
    for (virus_id,), found in files.groups(files.read(named), 1):
        if len(found) > 1:
            raise LoadError(
                f"virus {virus_id} has several names: "
                + ", ".join(repr(name) for _, name in found)
            )
    return named


def load_curated(
    export: Path,
    proteins: Path,
    scratch: Path,
    ontology: Ontology,
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
    with curated.open("w", encoding="utf-8") as out:
        by_second = scratch / "by_second"
        by_site = scratch / "by_site"
        with (
            by_second.open("w", encoding="utf-8") as hh,
            by_site.open("w", encoding="utf-8") as vh,
        ):
            for row in _on_host(by_first, proteins):
                if row.kind == InteractionKind.HH.value:
                    hh.write("\t".join([row.accession_2, *row]) + "\n")
                else:
                    vh.write(
                        "\t".join([row.accession_2, row.start_2, row.stop_2, *row])
                        + "\n"
                    )
        for row in _on_host(files.sort(by_second), proteins):
            out.write("\t".join(row) + "\n")
        with sites.open("w", encoding="utf-8") as observed:
            exported = _viral_sites(files.sort(by_site), export, scratch, out, observed)
    return CuratedFiles(curated, sites, exported, _viruses(curated, scratch))
