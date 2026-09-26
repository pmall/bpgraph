"""The curation export: our HH and VH descriptions, and the peptides they report.

The format is documented in docs/export.md. `descriptions.tsv` holds one row
per observation and restates both partners inline; `peptides.tsv` the peptides
a description reports. Which silo a row feeds follows from its `type`: an `hh`
row is our curation of the human interactome, merged onto IntAct by the host
loader; a `vh` row is a viral probe, read by the viral loader.

Human or viral is not a column either. A `vh` row's second partner is the
viral one, and every other partner is human. Of a human partner, only the
accession is read: its name and description come from Swiss-Prot.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.loaders.tsv import Cursor, choice, integer, required, rows, text
from bpgraph.psimi import Ontology
from bpgraph.uniprot import Site

DESCRIPTIONS = "descriptions.tsv"
PEPTIDES = "peptides.tsv"

INTERACTION_KINDS: Mapping[str, InteractionKind] = {
    "hh": InteractionKind.HH,
    "vh": InteractionKind.VH,
}
"""The `type` column. Lowercase in the export, a node label in the graph."""


@dataclass(frozen=True, slots=True)
class Mention:
    """One partner as one description row names it, before reconciliation."""

    accession: str
    start: int
    stop: int
    kind: ProteinKind
    name: str
    description: str
    taxon_id: int

    @property
    def site(self) -> Site:
        return (self.accession, self.start, self.stop)


@dataclass(frozen=True, slots=True)
class ExportRow:
    """One row of `descriptions.tsv`, its method already a current PSI-MI id."""

    cursor: Cursor
    stable_id: str
    kind: InteractionKind
    pmid: str
    psimi_id: str
    first: Mention
    second: Mention


@dataclass(frozen=True, slots=True)
class PeptideReference:
    """A `peptides.tsv` row, before its source is matched to a partner.

    The row names the source in full — kind, accession and span — so it is
    matched against where each of the description's partners was seen. A
    human partner is its whole entry, so there the accession alone decides.
    """

    cursor: Cursor
    sequence: str
    kind: ProteinKind
    site: Site

    def names(self, kind: ProteinKind, site: Site) -> bool:
        if self.kind is not kind:
            return False
        if kind is ProteinKind.HUMAN:
            return self.site[0] == site[0]
        return self.site == site


def _kind(cursor: Cursor, row: Mapping[str, str]) -> InteractionKind:
    value = required(cursor, row, "type")
    kind = INTERACTION_KINDS.get(value)
    if kind is None:
        allowed = ", ".join(sorted(INTERACTION_KINDS))
        raise cursor.fail(f"type must be one of {allowed}, not {value!r}")
    return kind


def _mention(
    cursor: Cursor, row: Mapping[str, str], slot: str, kind: ProteinKind
) -> Mention:
    return Mention(
        accession=required(cursor, row, f"accession{slot}"),
        start=integer(cursor, row, f"start{slot}"),
        stop=integer(cursor, row, f"stop{slot}"),
        kind=kind,
        name=required(cursor, row, f"name{slot}"),
        description=text(cursor, row, f"description{slot}"),
        taxon_id=integer(cursor, row, f"ncbi_taxon_id{slot}"),
    )


def export_rows(export: Path, ontology: Ontology) -> Iterator[ExportRow]:
    """Every row of `descriptions.tsv`. A `stable_id` is unique, and a method
    PSI-MI does not know fails the row."""
    seen: set[str] = set()
    for cursor, row in rows(export / DESCRIPTIONS):
        stable_id = required(cursor, row, "stable_id")
        if stable_id in seen:
            raise cursor.fail(f"stable_id {stable_id!r} appears twice")
        seen.add(stable_id)
        kind = _kind(cursor, row)
        declared = required(cursor, row, "psimi_id")
        psimi_id = ontology.canonical(declared)
        if psimi_id is None:
            raise cursor.fail(f"{declared} is not a PSI-MI term")
        second = ProteinKind.VIRAL if kind is InteractionKind.VH else ProteinKind.HUMAN
        yield ExportRow(
            cursor=cursor,
            stable_id=stable_id,
            kind=kind,
            pmid=required(cursor, row, "pmid"),
            psimi_id=psimi_id,
            first=_mention(cursor, row, "1", ProteinKind.HUMAN),
            second=_mention(cursor, row, "2", second),
        )


def peptide_references(export: Path) -> dict[str, list[PeptideReference]]:
    """The rows of `peptides.tsv`, grouped by description `stable_id`. Their
    source is resolved later, against the partners of the description."""
    grouped: dict[str, list[PeptideReference]] = {}
    path = export / PEPTIDES
    if not path.exists():
        return grouped
    for cursor, row in rows(path):
        reference = PeptideReference(
            cursor=cursor,
            sequence=required(cursor, row, "sequence").upper(),
            kind=choice(cursor, row, "source_type", ProteinKind),
            site=(
                required(cursor, row, "source_accession"),
                integer(cursor, row, "source_start"),
                integer(cursor, row, "source_stop"),
            ),
        )
        grouped.setdefault(required(cursor, row, "stable_id"), []).append(reference)
    return grouped


def export_pmids(export: Path, kind: InteractionKind) -> set[str]:
    """The pmids the export's rows of one type cite, without validating them."""
    return {
        required(cursor, row, "pmid")
        for cursor, row in rows(export / DESCRIPTIONS)
        if _kind(cursor, row) is kind
    }


def viral_sites(export: Path) -> list[Site]:
    """Every entry and span a viral partner was observed at."""
    return sorted(
        {
            _mention(cursor, row, "2", ProteinKind.VIRAL).site
            for cursor, row in rows(export / DESCRIPTIONS)
            if _kind(cursor, row) is InteractionKind.VH
        }
    )
