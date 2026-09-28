"""The curation export: our HH and VH descriptions, the viral proteins they
name, and the peptides they report.

The format is documented in docs/export.md. `descriptions_hh.tsv` and
`descriptions_vh.tsv` hold one row per observation and restate both partners
inline; `viral_proteins.tsv` the sequence of every viral partner;
`peptides.tsv` the peptides a description reports. Which silo a row feeds
follows from its file: an `hh` row is our curation of the human interactome,
merged onto IntAct; a `vh` row is a viral probe.

Human or viral is not a column either. A `vh` row's second partner is the
viral one, and every other partner is human. Of a human partner, only the
accession is read: its name and description come from Swiss-Prot.

Every reader here yields one validated row at a time, with the file and line
it came from.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.loaders.tsv import Cursor, choice, integer, required, rows
from bpgraph.psimi import Ontology

DESCRIPTIONS: Mapping[InteractionKind, str] = {
    InteractionKind.HH: "descriptions_hh.tsv",
    InteractionKind.VH: "descriptions_vh.tsv",
}
VIRAL_PROTEINS = "viral_proteins.tsv"
PEPTIDES = "peptides.tsv"

PMID = re.compile(r"^\d+$")
RESIDUES = re.compile(r"^[A-Z]+$")


@dataclass(frozen=True, slots=True)
class Mention:
    """One partner as one description row names it."""

    accession: str
    start: int
    stop: int
    name: str
    taxon_id: int


@dataclass(frozen=True, slots=True)
class ExportRow:
    """One description row, its method already a current PSI-MI id."""

    cursor: Cursor
    stable_id: str
    kind: InteractionKind
    pmid: str
    psimi_id: str
    first: Mention
    second: Mention


@dataclass(frozen=True, slots=True)
class ViralProtein:
    """One row of `viral_proteins.tsv`: a viral partner as curation holds it,
    and its residues."""

    cursor: Cursor
    accession: str
    start: int
    stop: int
    name: str
    taxon_id: int
    sequence: str


@dataclass(frozen=True, slots=True)
class PeptideRow:
    """One row of `peptides.tsv`, its source not yet matched to a partner."""

    cursor: Cursor
    stable_id: str
    sequence: str
    kind: ProteinKind
    accession: str
    start: int
    stop: int


def _pmid(cursor: Cursor, row: Mapping[str, str]) -> str:
    pmid = required(cursor, row, "pmid")
    if not PMID.match(pmid):
        raise cursor.fail(f"pmid is not digits: {pmid!r}")
    return pmid


def _mention(cursor: Cursor, row: Mapping[str, str], slot: str) -> Mention:
    return Mention(
        accession=required(cursor, row, f"accession{slot}"),
        start=integer(cursor, row, f"start{slot}"),
        stop=integer(cursor, row, f"stop{slot}"),
        name=required(cursor, row, f"name{slot}"),
        taxon_id=integer(cursor, row, f"ncbi_taxon_id{slot}"),
    )


def export_rows(export: Path, ontology: Ontology) -> Iterator[ExportRow]:
    """Every description row, HH then VH. A method PSI-MI does not know fails
    the row."""
    for kind, name in DESCRIPTIONS.items():
        for cursor, row in rows(export / name):
            declared = required(cursor, row, "psimi_id")
            psimi_id = ontology.canonical(declared)
            if psimi_id is None:
                raise cursor.fail(f"{declared} is not a PSI-MI term")
            yield ExportRow(
                cursor=cursor,
                stable_id=required(cursor, row, "stable_id"),
                kind=kind,
                pmid=_pmid(cursor, row),
                psimi_id=psimi_id,
                first=_mention(cursor, row, "1"),
                second=_mention(cursor, row, "2"),
            )


def viral_proteins(export: Path) -> Iterator[ViralProtein]:
    """Every viral entry and span, with its residues, which must span its
    coordinates exactly."""
    for cursor, row in rows(export / VIRAL_PROTEINS):
        start, stop = integer(cursor, row, "start"), integer(cursor, row, "stop")
        sequence = required(cursor, row, "sequence").upper()
        if len(sequence) != stop - start + 1:
            raise cursor.fail(f"{len(sequence)} residues for the span {start}-{stop}")
        yield ViralProtein(
            cursor=cursor,
            accession=required(cursor, row, "accession"),
            start=start,
            stop=stop,
            name=required(cursor, row, "name"),
            taxon_id=integer(cursor, row, "ncbi_taxon_id"),
            sequence=sequence,
        )


def peptide_rows(export: Path) -> Iterator[PeptideRow]:
    """The rows of `peptides.tsv`."""
    for cursor, row in rows(export / PEPTIDES):
        sequence = required(cursor, row, "sequence").upper()
        if not RESIDUES.match(sequence):
            raise cursor.fail(f"sequence is not residues: {sequence!r}")
        yield PeptideRow(
            cursor=cursor,
            stable_id=required(cursor, row, "stable_id"),
            sequence=sequence,
            kind=choice(cursor, row, "source_type", ProteinKind),
            accession=required(cursor, row, "source_accession"),
            start=integer(cursor, row, "source_start"),
            stop=integer(cursor, row, "source_stop"),
        )


def export_pmids(export: Path, kind: InteractionKind) -> Iterator[str]:
    """The pmids the export's rows of one type cite, without validating them."""
    for cursor, row in rows(export / DESCRIPTIONS[kind]):
        yield required(cursor, row, "pmid")
