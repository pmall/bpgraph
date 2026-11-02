"""The curation export: our HH and VH descriptions, the viral sites they
observe, and the peptides they report.

The relational database exports five TSV files, read as `bpgraph.loaders.tsv`
says, into a run's `export/`, `_data/2026-10-14/export/`. It names each after
the run that wrote it, `descriptions_hh_run87.tsv`, so a file is found by its
stem, and an export holds exactly one file of each stem. The `.xlsx` copy the
database also writes of each is ignored.

- `descriptions_hh`, one row per human–human observation: a pair, a pmid, a
  method; `descriptions_vh`, one per virus–human observation. `ExportRow`.
- `interactors_viral`, one row per viral entry and span a VH row names, with
  its residues. `ViralSite`.
- `mappings_h` and `mappings_v`, one row per sequence a description maps on
  one of its partners. `PeptideRow`.

The export carries only what our curation alone knows: our interactions, how
the viral proteins they name are grouped, the viral sequences, and the
sequences the interactions map. Everything a public source knows better comes
from that source, fetched into the run beside the export: a human protein's
name and function from Swiss-Prot, a viral entry's function text from UniProt,
a method's name from PSI-MI, a publication's metadata from PubMed.

Which silo a row feeds follows from its file: an `hh` row is our curation of
the human interactome, which stands for its publication in place of IntAct's
records, as `bpgraph.loaders.host` says; a `vh` row is a viral probe. Human or
viral is not a column either: slot 1 is always the human partner, a `vh` row's
second partner is the viral one, and every other partner is human. Two viral
proteins may not interact, so there is no `vv` file. A pair may be one protein
twice, a homodimer.

**UniProt entries are the ones curation recorded.** A human accession is a
Swiss-Prot entry of the current release, canonical, not an isoform's;
`bpgraph.loaders.curated` drops a row naming any other. A viral entry may be of
any release: curation matches its entries to the current UniProt where it can,
and keeps the recorded one where it cannot. Each partner says which release it
is of, and a viral site's coordinates and sequence are that release's.

**Curation groups the viral proteins**, and the build takes the grouping as
given: a viral partner's virus is the row's species taxon, and its protein the
virus plus the row's `protein`, a name grouping its curated forms: HBV's `X`
and `HBx` are both `HBx`, EBV's `EBNA6` is `EBNA3C`. docs/schema.md says what
they become.

Every reader here yields one validated row at a time, with the file and line
it came from, so a malformed export fails before anything is written:
`descriptions_vh_run87.tsv:2: MI:9999 is not a PSI-MI term`.
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
    """The viral partner of a VH row, as curation groups it, from the columns
    of `descriptions_vh`:

    - `accession2`, `start2`, `stop2`: the entry and span it was observed at,
      1-based inclusive;
    - `release2`: the UniProt release of the entry, which must be the one its
      row of `interactors_viral` gives;
    - `protein`: the curated protein name, case-sensitive, as part of the
      protein's identity;
    - `species_ncbi_taxon_id`, `species`: the virus, the species taxon curation
      groups the protein under, and its name;
    - `strain_ncbi_taxon_id`, `strain`: the entry's strain, kept in the vault;
      `strain` may be empty;
    - `uniprot_name2`, `generic_name2`: not read.
    """

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
    """One row of `descriptions_hh` or `descriptions_vh`, one description: one
    protein pair, one publication, one method. `second` is the second
    partner's accession, and `viral` is set for a VH row alone.

    The columns both files share:

    - `stable_id`: curation's identifier, the description's key, so unique
      across the two files;
    - `pmid`: digits only;
    - `psimi_id`: a PSI-MI id, or a secondary id PSI-MI maps to its term's,
      which the row then carries;
    - `accession1`: the first partner, always human;
    - `version`, `method`, `release1`, `gene_name1`: not read: the row's
      revision, the method's name, which PSI-MI gives, and the partner's
      release and gene name, which Swiss-Prot gives.

    `descriptions_hh` names its second partner, human, the same way:
    `accession2`, with `release2` and `gene_name2` unread. `descriptions_vh`
    names its viral partner as `ViralMention` says.
    """

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
    """One row of `interactors_viral`: a viral entry and span a VH row names,
    and its residues in the UniProt release curation recorded them from. Every
    viral partner of `descriptions_vh` must have its row. The residues go to
    the viral vault, not the graph.

    - `accession`, `start`, `stop`: the entry and span, as the descriptions
      name them;
    - `release`: the UniProt release the sequence is from;
    - `sequence`: the residues of that span, exactly `stop - start + 1`,
      uppercased on load.
    """

    cursor: Cursor
    accession: str
    start: int
    stop: int
    release: str
    sequence: str


@dataclass(frozen=True, slots=True)
class PeptideRow:
    """One row of `mappings_h` or `mappings_v` that is a peptide, its source
    not yet matched to a partner.

    A mapping is a sequence a description maps on one of its partners: the
    region it reports as sufficient for the interaction. A description may map
    none, or several. `mappings_h` holds the ones on a human partner,
    `mappings_v` the ones on a viral partner:

    - `stable_id`: the description's, which must be in a description file;
    - `sequence`: the residues, uppercased on load, so a lowercase residue is
      taken as given;
    - `accession`: the partner it is on, its source, which must be one of the
      description's two; a mapping on an isoform is its entry's;
    - `start`, `stop`: `mappings_v` only, the viral partner's span, which must
      be the description's;
    - `target`: `mappings_h` only, `h` or `v`, the kind of the partner the
      sequence binds;
    - `isoform`, `release`, `nter`, `cter`: not read.

    Every mapping's sequence must be letters. Only a peptide is kept, 5 to 20
    residues, both included: a longer or shorter mapping is skipped without
    being checked further. `start` and `stop` are a viral source's span, and
    `0` for a human source, which is its whole entry. `target` is the kind of
    the partner it binds: a viral source binds a human one.
    """

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
