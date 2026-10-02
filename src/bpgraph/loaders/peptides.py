"""The peptides our curated rows report, placed on the descriptions the rows
became.

A peptide names its curated row and its source in full: `h` or `v`, entry and
span. The source must be one of that row's partners — a human one by accession
alone, since a human partner is its whole entry — and is the protein the
peptide was cut from; the other partner is the one it binds, and a homodimer's
peptide binds its own source. A dropped row drops its peptides; a peptide
naming no row at all fails the build.
"""

from collections.abc import Iterator
from pathlib import Path

from bpgraph import files
from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.loaders.export import peptide_rows
from bpgraph.loaders.records import KEPT, Curated, Description, Report, of
from bpgraph.loaders.tsv import Cursor


def _source(
    row: Curated, kind: str, accession: str, start: str, stop: str
) -> str | None:
    """The reference of the protein a peptide's source names, if it is one of
    the row's partners."""
    if kind == ProteinKind.HUMAN.value:
        humans = [row.accession_1]
        if row.kind == InteractionKind.HH.value:
            humans.append(row.accession_2)
        return accession if accession in humans else None
    if row.kind == InteractionKind.VH.value and (accession, start, stop) == row.site_2:
        return row.partner_2
    return None


def _sources(export: Path, curated: Path, scratch: Path) -> Iterator[list[str]]:
    """`[stable_id, sequence, source]` for every peptide of a kept row."""
    peptides = files.sorted_file(
        scratch / "peptides_by_row",
        (
            [
                p.stable_id,
                p.sequence,
                p.kind.value,
                p.accession,
                str(p.start),
                str(p.stop),
                str(p.cursor.path),
                str(p.cursor.line),
            ]
            for p in peptide_rows(export)
        ),
    )
    rows = files.sorted_file(scratch / "curated_by_id", files.read(curated))
    for (stable_id,), found, owner in files.cogroup(
        files.read(peptides), files.read(rows), 1
    ):
        if not found:
            continue
        if not owner:
            path, line = found[0][6], found[0][7]
            raise Cursor(Path(path), int(line)).fail(
                f"{stable_id} is not in the description files"
            )
        row = of(Curated, owner[0])
        if row.status != KEPT:
            continue
        for _, sequence, kind, accession, start, stop, path, line in found:
            source = _source(row, kind, accession, start, stop)
            if source is None:
                raise Cursor(Path(path), int(line)).fail(
                    f"source {accession}:{start}-{stop} is not a partner of {stable_id}"
                )
            yield [stable_id, sequence, source]


def reports(export: Path, curated: Path, descriptions: Path, scratch: Path) -> Path:
    """Every peptide a curated description reports, once per sequence and
    source, sorted by interaction."""
    sources = files.sorted_file(
        scratch / "peptide_sources", _sources(export, curated, scratch)
    )
    owners = files.sorted_file(
        scratch / "description_by_row",
        (
            [d.stable_id, d.interaction, d.side_a, d.side_b]
            for d in (of(Description, r) for r in files.read(descriptions))
            if d.stable_id
        ),
    )

    def placed() -> Iterator[list[str]]:
        for (stable_id,), found, owner in files.cogroup(
            files.read(sources), files.read(owners), 1
        ):
            if not found:
                continue
            _, interaction, side_a, side_b = owner[0]
            for _, sequence, source in found:
                target = side_b if source == side_a else side_a
                yield list(Report(interaction, stable_id, sequence, source, target))

    return files.sorted_file(scratch / "reports", placed(), unique=True)
