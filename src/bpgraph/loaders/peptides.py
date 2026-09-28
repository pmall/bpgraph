"""The peptides our curated rows report, placed on the descriptions the rows
became.

A peptide names its curated row and its source in full: `h` or `v`, entry and
span. The source must be one of that row's partners — a human one by accession
alone, since a human partner is its whole entry — and is the side the peptide
comes from; the other side is its target. A curated row merged onto an IntAct
description brings its peptides to that description. A dropped row drops its
peptides; a peptide naming no row at all fails the build.
"""

from collections.abc import Iterator
from pathlib import Path

from bpgraph import files
from bpgraph.enums import InteractionKind, ProteinKind, Side
from bpgraph.loaders.export import peptide_rows
from bpgraph.loaders.records import KEPT, Curated, Description, Report, of
from bpgraph.loaders.tsv import Cursor


def _source(
    row: Curated, kind: str, accession: str, start: str, stop: str
) -> str | None:
    """The protein id a peptide's source names, if it is one of the row's
    partners."""
    if kind == ProteinKind.HUMAN.value:
        humans = [row.accession_1]
        if row.kind == InteractionKind.HH.value:
            humans.append(row.accession_2)
        return accession if accession in humans else None
    if row.kind == InteractionKind.VH.value and (accession, start, stop) == row.site_2:
        return row.partner_2
    return None


def _sources(export: Path, curated: Path, scratch: Path) -> Iterator[list[str]]:
    """`[stable_id, sequence, source_id]` for every peptide of a kept row."""
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
    """Every peptide a description reports, once per sequence and side, sorted
    by interaction."""
    sources = files.sorted_file(
        scratch / "peptide_sources", _sources(export, curated, scratch)
    )
    owners = files.sorted_file(
        scratch / "description_by_row",
        (
            [stable_id, d.id, d.interaction_id, d.side_a]
            for d in (of(Description, r) for r in files.read(descriptions))
            for stable_id in d.stable_ids.split(";")
            if stable_id
        ),
    )

    def placed() -> Iterator[list[str]]:
        for _, found, owner in files.cogroup(
            files.read(sources), files.read(owners), 1
        ):
            if not found:
                continue
            _, description_id, interaction, side_a = owner[0]
            for _, sequence, source in found:
                side = Side.A if source == side_a else Side.B
                yield list(Report(interaction, description_id, sequence, side.value))

    return files.sorted_file(scratch / "reports", placed(), unique=True)
