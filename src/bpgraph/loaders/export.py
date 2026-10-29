"""The curation export: our HH and VH descriptions, the viral sites they
observe, and the peptides they report.

The format is documented in docs/export.md. `descriptions_hh` and
`descriptions_vh` hold one row per observation and restate both partners
inline; `interactors_viral` the sequence of every viral site; `mappings_h` and
`mappings_v` the sequences the descriptions map, from a human and a viral
partner. Which silo a row feeds follows from its file: an `hh` row is our
curation of the human interactome, merged onto IntAct; a `vh` row is a viral
probe.

The database names each file after the run that wrote it,
`descriptions_hh_run87.tsv`, so a file is found by its stem: exactly one
`descriptions_hh*.tsv` per export.

Human or viral is not a column either. A `vh` row's second partner is the
viral one, and every other partner is human. Of a human partner, only the
accession is read: its name and description come from Swiss-Prot. A viral
partner is grouped by curation: its virus is the row's species taxon and its
name the row's `protein`.

Every reader here yields one validated row at a time, with the file and line
it came from.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.loaders.tsv import Cursor, LoadError, choice, integer, required, rows, text
from bpgraph.psimi import Ontology

DESCRIPTIONS: Mapping[InteractionKind, str] = {
    InteractionKind.HH: "descriptions_hh",
    InteractionKind.VH: "descriptions_vh",
}
VIRAL_SITES = "interactors_viral"
MAPPINGS: Mapping[ProteinKind, str] = {
    ProteinKind.HUMAN: "mappings_h",
    ProteinKind.VIRAL: "mappings_v",
}

PEPTIDE_LENGTHS = range(5, 21)
"""A mapped sequence is a peptide from 5 to 20 residues, both included."""

PMID = re.compile(r"^\d+$")
RESIDUES = re.compile(r"^[A-Z]+$")


def export_file(export: Path, stem: str) -> Path:
    """The one file of the export a stem names, whatever run suffix the
    database gave it."""
    found = sorted(export.glob(f"{stem}*.tsv"))
    if len(found) != 1:
        named = ", ".join(path.name for path in found) or "none"
        raise LoadError(f"{export}: one {stem}*.tsv expected, found {named}")
    return found[0]


@dataclass(frozen=True, slots=True)
class ViralMention:
    """The viral partner of a VH row, as curation groups it."""

    accession: str
    start: int
    stop: int
    name: str
    virus_id: int
    virus_name: str
    strain_id: int
    strain_name: str
    release: str


@dataclass(frozen=True, slots=True)
class ExportRow:
    """One description row, its method already a current PSI-MI id. `second`
    is the second partner's accession for an HH row, and `viral` is set for a
    VH row alone."""

    cursor: Cursor
    stable_id: str
    kind: InteractionKind
    pmid: str
    psimi_id: str
    first: str
    second: str
    viral: ViralMention | None


@dataclass(frozen=True, slots=True)
class ViralSite:
    """One row of `interactors_viral`: a viral entry and span, and its
    residues in the UniProt release curation recorded them from."""

    cursor: Cursor
    accession: str
    start: int
    stop: int
    release: str
    sequence: str


@dataclass(frozen=True, slots=True)
class PeptideRow:
    """One mapping of 5 to 20 residues, its source not yet matched to a
    partner. `start` and `stop` are a viral source's span, and `0` for a human
    source, which is its whole entry. `target` is the kind of the partner it
    binds."""

    cursor: Cursor
    stable_id: str
    sequence: str
    kind: ProteinKind
    accession: str
    start: int
    stop: int
    target: ProteinKind


def _pmid(cursor: Cursor, row: Mapping[str, str]) -> str:
    pmid = required(cursor, row, "pmid")
    if not PMID.match(pmid):
        raise cursor.fail(f"pmid is not digits: {pmid!r}")
    return pmid


def _viral(cursor: Cursor, row: Mapping[str, str]) -> ViralMention:
    return ViralMention(
        accession=required(cursor, row, "accession2"),
        start=integer(cursor, row, "start2"),
        stop=integer(cursor, row, "stop2"),
        name=required(cursor, row, "protein"),
        virus_id=integer(cursor, row, "species_ncbi_taxon_id"),
        virus_name=required(cursor, row, "species"),
        strain_id=integer(cursor, row, "strain_ncbi_taxon_id"),
        strain_name=text(cursor, row, "strain"),
        release=required(cursor, row, "release2"),
    )


def export_rows(export: Path, ontology: Ontology) -> Iterator[ExportRow]:
    """Every description row, HH then VH. A method PSI-MI does not know fails
    the row."""
    for kind, stem in DESCRIPTIONS.items():
        for cursor, row in rows(export_file(export, stem)):
            declared = required(cursor, row, "psimi_id")
            psimi_id = ontology.canonical(declared)
            if psimi_id is None:
                raise cursor.fail(f"{declared} is not a PSI-MI term")
            viral = _viral(cursor, row) if kind is InteractionKind.VH else None
            yield ExportRow(
                cursor=cursor,
                stable_id=required(cursor, row, "stable_id"),
                kind=kind,
                pmid=_pmid(cursor, row),
                psimi_id=psimi_id,
                first=required(cursor, row, "accession1"),
                second=viral.accession
                if viral
                else required(cursor, row, "accession2"),
                viral=viral,
            )


def viral_sites(export: Path) -> Iterator[ViralSite]:
    """Every viral entry and span, with its residues, which must span its
    coordinates exactly."""
    for cursor, row in rows(export_file(export, VIRAL_SITES)):
        start, stop = integer(cursor, row, "start"), integer(cursor, row, "stop")
        sequence = required(cursor, row, "sequence").upper()
        if len(sequence) != stop - start + 1:
            raise cursor.fail(f"{len(sequence)} residues for the span {start}-{stop}")
        yield ViralSite(
            cursor=cursor,
            accession=required(cursor, row, "accession"),
            start=start,
            stop=stop,
            release=required(cursor, row, "release"),
            sequence=sequence,
        )


def peptide_rows(export: Path) -> Iterator[PeptideRow]:
    """The mappings of both files that are peptides: 5 to 20 residues. A
    mapping on an isoform is its entry's; where it starts and ends on the
    source is not read."""
    for kind, stem in MAPPINGS.items():
        for cursor, row in rows(export_file(export, stem)):
            sequence = required(cursor, row, "sequence").upper()
            if not RESIDUES.match(sequence):
                raise cursor.fail(f"sequence is not residues: {sequence!r}")
            if len(sequence) not in PEPTIDE_LENGTHS:
                continue
            viral = kind is ProteinKind.VIRAL
            yield PeptideRow(
                cursor=cursor,
                stable_id=required(cursor, row, "stable_id"),
                sequence=sequence,
                kind=kind,
                accession=required(cursor, row, "accession"),
                start=integer(cursor, row, "start") if viral else 0,
                stop=integer(cursor, row, "stop") if viral else 0,
                target=(
                    ProteinKind.HUMAN
                    if viral
                    else choice(cursor, row, "target", ProteinKind)
                ),
            )


def export_pmids(export: Path, kind: InteractionKind) -> Iterator[str]:
    """The pmids the export's rows of one type cite, without validating them."""
    for cursor, row in rows(export_file(export, DESCRIPTIONS[kind])):
        yield required(cursor, row, "pmid")
