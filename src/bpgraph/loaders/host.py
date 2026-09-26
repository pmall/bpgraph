"""A host species' silo: its proteome, its interactions, its GO.

Everything here comes from what was fetched for the host alone — Swiss-Prot,
IntAct, GOA — plus, for human, our own curation of the human interactome from
the export. Nothing is read from another silo.

- **Proteins** are every Swiss-Prot entry of the host, with or without an
  interaction: name, description, function text, and the publications that
  text cites.
- **Interactions** are IntAct's, with our curated rows merged onto them. A
  curated row *is* an IntAct description when both have the same pair, the same
  pmid and the same method class; it then adds its `stable_id` to that
  description rather than a description of its own. One IntAct pmid may hold
  several descriptions of one pair in one class, and a curated row goes to the
  one with the lowest IntAct id, so a build is deterministic. A curated row
  IntAct has not got is a description of its own, and a new interaction if
  IntAct has none for that pair.
- **GO annotations** are the experimental ones, one per publication.

A curated row whose partner is not in Swiss-Prot — an accession UniProt has
merged, demerged or deleted since it was curated — is dropped and logged, not
a failure. So is a row coded `MI:0000`, the root of PSI-MI, which says nothing
about the method.
"""

import logging
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.go import read_annotations_file
from bpgraph.ids import human_protein_id, intact_description_id
from bpgraph.loaders.export import ExportRow, PeptideReference, export_pmids
from bpgraph.loaders.tsv import LoadError, make, required, rows
from bpgraph.methods import ROOT
from bpgraph.models import (
    Description,
    FunctionCitation,
    GoAnnotation,
    Peptide,
    Protein,
    ProteinRef,
    ReportedPeptide,
)
from bpgraph.run import HostPaths, Run
from bpgraph.swissprot import read_swissprot
from bpgraph.vault import HostVault

logger = logging.getLogger(__name__)

type _Key = tuple[str, str, str, str]
"""What makes a curated row one of IntAct's: pair, pmid, method class."""


@dataclass(frozen=True, slots=True)
class HostSilo:
    """What one host contributes to a build."""

    taxon_id: int
    proteins: Mapping[str, Protein]
    citations: tuple[FunctionCitation, ...]
    descriptions: tuple[Description, ...]
    annotations: tuple[GoAnnotation, ...]
    vault: HostVault
    stable_ids: frozenset[str]
    """The curated rows this silo read, kept or dropped: their peptides are
    this silo's to place."""


@dataclass(slots=True)
class _Draft:
    """A description before its peptides are resolved."""

    id: str
    intact_id: str
    accession_a: str
    accession_b: str
    pmid: str
    psimi_id: str
    stable_ids: list[str] = field(default_factory=list)


def _intact_order(intact_id: str) -> tuple[int, str]:
    """IntAct ids by number: `EBI-99` before `EBI-100`."""
    digits = intact_id.rpartition("-")[2]
    return (int(digits) if digits.isdigit() else sys.maxsize, intact_id)


def _intact(host: HostPaths) -> Iterator[_Draft]:
    for cursor, row in rows(host.intact):
        intact_id = required(cursor, row, "intact_id")
        first, second = sorted(
            (required(cursor, row, "accession1"), required(cursor, row, "accession2"))
        )
        yield _Draft(
            id=intact_description_id(intact_id, first, second),
            intact_id=intact_id,
            accession_a=first,
            accession_b=second,
            pmid=required(cursor, row, "pmid"),
            psimi_id=required(cursor, row, "psimi_id"),
        )


def _consolidate(
    host: HostPaths,
    curated: Sequence[ExportRow],
    proteins: Mapping[str, Protein],
    classes: Mapping[str, str],
) -> list[_Draft]:
    """IntAct's descriptions, with our curated rows merged onto them."""
    drafts: dict[str, _Draft] = {}
    matches: dict[_Key, list[_Draft]] = {}
    for draft in _intact(host):
        if draft.id in drafts:
            raise LoadError(f"{host.intact.name}: {draft.id} appears twice")
        drafts[draft.id] = draft
        key = (
            draft.accession_a,
            draft.accession_b,
            draft.pmid,
            classes[draft.psimi_id],
        )
        matches.setdefault(key, []).append(draft)
    for candidates in matches.values():
        candidates.sort(key=lambda d: _intact_order(d.intact_id))
    intact_pairs = {(d.accession_a, d.accession_b) for d in drafts.values()}

    dropped: Counter[str] = Counter()
    unknown: set[str] = set()
    merged = 0
    new_pairs: set[tuple[str, str]] = set()
    for row in curated:
        if row.psimi_id == ROOT:
            dropped[f"coded {ROOT}"] += 1
            continue
        absent = [
            m.accession for m in (row.first, row.second) if m.accession not in proteins
        ]
        if absent:
            unknown.update(absent)
            dropped["partner not in swiss-prot"] += 1
            continue
        first, second = sorted((row.first.accession, row.second.accession))
        candidates = matches.get((first, second, row.pmid, classes[row.psimi_id]))
        if candidates:
            candidates[0].stable_ids.append(row.stable_id)
            merged += 1
            continue
        if row.stable_id in drafts:
            raise row.cursor.fail(f"stable_id {row.stable_id} collides with an id")
        drafts[row.stable_id] = _Draft(
            id=row.stable_id,
            intact_id="",
            accession_a=first,
            accession_b=second,
            pmid=row.pmid,
            psimi_id=row.psimi_id,
            stable_ids=[row.stable_id],
        )
        if (first, second) not in intact_pairs:
            new_pairs.add((first, second))

    kept = len(curated) - sum(dropped.values())
    on_new_pairs = sum(
        1
        for d in drafts.values()
        if not d.intact_id and (d.accession_a, d.accession_b) in new_pairs
    )
    logger.info(
        "%d HH: %d IntAct descriptions; of %d curated rows, %d are IntAct's and "
        "%d are not, %d of them on %d pairs IntAct has no interaction for",
        host.taxon_id,
        len(drafts) - (kept - merged),
        kept,
        merged,
        kept - merged,
        on_new_pairs,
        len(new_pairs),
    )
    for reason, count in dropped.items():
        logger.warning(
            "%d HH: dropped %d curated rows: %s", host.taxon_id, count, reason
        )
    if unknown:
        logger.warning(
            "%d HH: %d curated accessions are not in Swiss-Prot: %s",
            host.taxon_id,
            len(unknown),
            ", ".join(sorted(unknown)),
        )
    return list(drafts.values())


def _peptides(
    draft: _Draft,
    partners: Sequence[ProteinRef],
    references: Mapping[str, list[PeptideReference]],
) -> tuple[ReportedPeptide, ...]:
    """The peptides every curated row behind a description reports, once per
    sequence and source. A source that is not one of the partners fails the
    peptide's row."""
    unique: dict[tuple[str, str], ReportedPeptide] = {}
    for stable_id in draft.stable_ids:
        for reference in references.get(stable_id, ()):
            source = next(
                (
                    p
                    for p in partners
                    if reference.kind is ProteinKind.HUMAN and reference.site[0] == p.id
                ),
                None,
            )
            if source is None:
                accession, start, stop = reference.site
                raise reference.cursor.fail(
                    f"source {accession}:{start}-{stop} is not a partner of {draft.id}"
                )
            reported = make(
                reference.cursor,
                ReportedPeptide,
                peptide=make(reference.cursor, Peptide, sequence=reference.sequence),
                source=source,
            )
            unique.setdefault((reference.sequence, source.id), reported)
    return tuple(unique.values())


def _descriptions(
    drafts: Iterable[_Draft],
    proteins: Mapping[str, Protein],
    references: Mapping[str, list[PeptideReference]],
) -> Iterator[Description]:
    for draft in drafts:
        partners = (proteins[draft.accession_a], proteins[draft.accession_b])
        refs = tuple(ProteinRef(id=p.id, kind=p.kind) for p in partners)
        yield Description(
            id=draft.id,
            intact_id=draft.intact_id,
            stable_ids=tuple(draft.stable_ids),
            partner_1=refs[0],
            partner_2=refs[1],
            pmid=draft.pmid,
            psimi_id=draft.psimi_id,
            peptides=_peptides(draft, refs, references),
        )


def _annotations(
    host: HostPaths, proteins: Mapping[str, Protein]
) -> Iterator[GoAnnotation]:
    for annotation in read_annotations_file(host.go_annotations):
        protein = proteins.get(human_protein_id(annotation.accession))
        if protein is None:
            raise LoadError(
                f"{host.go_annotations.name}: {annotation.accession} is not in "
                f"{host.swissprot.name}: fetch GO again"
            )
        yield GoAnnotation(
            protein=ProteinRef(id=protein.id, kind=protein.kind),
            go_id=annotation.go_id,
            qualifier=annotation.qualifier,
            evidence_code=annotation.evidence_code,
            assigned_by=annotation.assigned_by,
            pmid=annotation.pmid,
        )


def _sequences(host: HostPaths) -> dict[str, str]:
    return {
        required(cursor, row, "accession"): required(cursor, row, "sequence")
        for cursor, row in rows(host.sequences)
    }


def load_host(
    host: HostPaths,
    curated: Sequence[ExportRow],
    references: Mapping[str, list[PeptideReference]],
    classes: Mapping[str, str],
) -> HostSilo:
    """Load one host. `curated` are our rows of its interactome, and `classes`
    the method class of every PSI-MI term they or IntAct use."""
    entries = read_swissprot(host.swissprot)
    proteins = {
        human_protein_id(entry.accession): Protein(
            id=human_protein_id(entry.accession),
            kind=ProteinKind.HUMAN,
            name=entry.name,
            description=entry.description,
            function=entry.function,
        )
        for entry in entries.values()
    }
    citations = tuple(
        FunctionCitation(
            protein=ProteinRef(
                id=human_protein_id(entry.accession), kind=ProteinKind.HUMAN
            ),
            pmid=pmid,
        )
        for entry in entries.values()
        for pmid in entry.pmids
    )
    drafts = _consolidate(host, curated, proteins, classes)
    sequences = _sequences(host)
    missing = set(entries) - set(sequences)
    if missing:
        raise LoadError(
            f"{host.sequences.name} lacks {len(missing)} entries of "
            f"{host.swissprot.name}: fetch Swiss-Prot again"
        )
    return HostSilo(
        taxon_id=host.taxon_id,
        proteins=proteins,
        citations=citations,
        descriptions=tuple(_descriptions(drafts, proteins, references)),
        annotations=tuple(_annotations(host, proteins)),
        vault=HostVault(taxon_id=host.taxon_id, name=host.vault, sequences=sequences),
        stable_ids=frozenset(row.stable_id for row in curated),
    )


def host_pmids(run: Run, host: HostPaths) -> set[str]:
    """Every pmid the host's silo cites: IntAct, our curated rows of its
    interactome, its GO annotations and its function text."""
    pmids = {required(cursor, row, "pmid") for cursor, row in rows(host.intact)}
    pmids |= export_pmids(run.export, InteractionKind.HH)
    pmids |= {a.pmid for a in read_annotations_file(host.go_annotations)}
    pmids |= {
        p for entry in read_swissprot(host.swissprot).values() for p in entry.pmids
    }
    return pmids
