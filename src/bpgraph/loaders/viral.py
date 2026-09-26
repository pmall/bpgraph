"""The viral silo: our virus–host interactions, probing a host interactome.

A viral protein is a curated mature protein of a curated virus, whichever
strains and accessions it was observed on: its id is its virus and its name,
so every strain's copy of `HBx` lands on one protein. The export restates it
on every row it takes part in, so the rows are gathered first — into one draft
per protein, with the entries and spans it was seen at — and reconciled into
nodes after: a name or a description takes its commonest value.

Every viral taxon must find its virus in `curation/viruses.tsv`; a taxon no
row encloses fails the load. The host partner must be a Swiss-Prot entry of
the host; a row whose host partner is not is dropped and logged, as is a row
coded `MI:0000`.

Where each viral protein sits on each entry, the entry's strain and sequence,
and which entry each description used, go to the viral vault rather than the
graph.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from bpgraph.enums import InteractionKind, ProteinKind
from bpgraph.ids import viral_protein_id
from bpgraph.loaders.export import ExportRow, Mention, PeptideReference, export_pmids
from bpgraph.loaders.tsv import (
    Cursor,
    integer,
    listed,
    make,
    required,
    rows,
)
from bpgraph.methods import ROOT
from bpgraph.models import (
    Description,
    FunctionCitation,
    Membership,
    Peptide,
    Protein,
    ProteinRef,
    ReportedPeptide,
    Virus,
)
from bpgraph.run import Run, ViralPaths
from bpgraph.taxonomy import Taxonomy, TaxonomyUnavailable
from bpgraph.uniprot import Site
from bpgraph.vault import Mature, ViralEntry, ViralVault
from bpgraph.viruses import CuratedViruses

logger = logging.getLogger(__name__)

LENGTH_SPREAD = 0.5
"""A grouped viral protein whose shortest member is under half its longest is
reported: those members may not be one chain, and may not share one function."""


@dataclass(frozen=True, slots=True)
class ViralSilo:
    """What the viral silo contributes to a build."""

    proteins: Mapping[str, Protein]
    viruses: tuple[Virus, ...]
    memberships: tuple[Membership, ...]
    citations: tuple[FunctionCitation, ...]
    descriptions: tuple[Description, ...]
    vault: ViralVault
    stable_ids: frozenset[str]
    """The curated rows this silo read, kept or dropped."""


@dataclass(slots=True)
class _EntryDraft:
    """Every mention of one viral accession."""

    taxon_id: int
    taxon_name: str
    descriptions: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _ProteinDraft:
    """Every mention of one viral protein. The counters decide between the
    variants the rows restate, and `sites` is how often each entry and span
    carried it."""

    cursor: Cursor
    virus: int
    names: Counter[str] = field(default_factory=Counter)
    descriptions: Counter[str] = field(default_factory=Counter)
    sites: Counter[Site] = field(default_factory=Counter)


def _majority(values: Counter[str]) -> str:
    """The commonest value a column held. Every row restates it, and a few
    disagree — a UniProt name changed after some were written."""
    (value, _), *_ = values.most_common()
    return value


@dataclass(slots=True)
class _Registry:
    """The viral protein and entry tables, rebuilt from the export's rows."""

    taxonomy: Taxonomy
    curated: CuratedViruses
    entries: dict[str, _EntryDraft] = field(default_factory=dict)
    drafts: dict[str, _ProteinDraft] = field(default_factory=dict)
    taxa: dict[int, tuple[int, str]] = field(default_factory=dict)
    viruses: dict[int, Virus | None] = field(default_factory=dict)
    uncurated: set[int] = field(default_factory=set)

    def observe(self, cursor: Cursor, mention: Mention) -> None:
        taxon_id, taxon_name = self._taxon(cursor, mention.taxon_id)
        entry = self.entries.get(mention.accession)
        if entry is None:
            entry = _EntryDraft(taxon_id=taxon_id, taxon_name=taxon_name)
            self.entries[mention.accession] = entry
        elif entry.taxon_id != taxon_id:
            raise cursor.fail(
                f"{mention.accession} is taxon {entry.taxon_id} elsewhere and "
                f"{mention.taxon_id} here"
            )
        entry.descriptions[mention.description] += 1
        virus = self._virus(taxon_id)
        if virus is None:
            self.uncurated.add(taxon_id)
            return
        identity = viral_protein_id(virus.taxon_id, mention.name)
        draft = self.drafts.get(identity)
        if draft is None:
            draft = _ProteinDraft(cursor=cursor, virus=virus.taxon_id)
            self.drafts[identity] = draft
        draft.names[mention.name] += 1
        draft.descriptions[mention.description] += 1
        draft.sites[mention.site] += 1

    def identity(self, cursor: Cursor, mention: Mention) -> str:
        """The id of the protein a mention names."""
        virus = self._virus(self._taxon(cursor, mention.taxon_id)[0])
        if virus is None:
            raise cursor.fail(f"taxon {mention.taxon_id} has no curated virus")
        return viral_protein_id(virus.taxon_id, mention.name)

    def _taxon(self, cursor: Cursor, taxon_id: int) -> tuple[int, str]:
        """Canonicalize a taxon id and name it from the local taxonomy.

        The export carries whatever id was recorded at curation time; NCBI
        retires ids as it reorganizes, so this is where a legacy one becomes
        the current one. Memoized — a thousand distinct taxa are restated
        across a hundred thousand rows.
        """
        known = self.taxa.get(taxon_id)
        if known is not None:
            return known
        try:
            current = self.taxonomy.canonical(taxon_id)
        except TaxonomyUnavailable as error:
            raise cursor.fail(str(error)) from None
        resolved = (current, self.taxonomy.name(current))
        self.taxa[taxon_id] = resolved
        return resolved

    def _virus(self, taxon_id: int) -> Virus | None:
        if taxon_id not in self.viruses:
            self.viruses[taxon_id] = self.curated.enclosing(taxon_id)
        return self.viruses[taxon_id]

    def report(self) -> None:
        """The checks a human should look at, none of which stops a build.

        Names are case-sensitive, so names differing only in case are two
        proteins — genuinely so for EBV's `BARF1` and `BaRF1`, but any new pair
        is worth a look. And the entries of one grouped protein should be one
        chain: members whose lengths differ by more than half are listed.
        """
        by_folded: dict[tuple[int, str], set[str]] = {}
        for draft in self.drafts.values():
            name = _majority(draft.names)
            by_folded.setdefault((draft.virus, name.lower()), set()).add(name)
        collisions = sorted(
            f"{self.curated.viruses[virus].name} {'/'.join(sorted(names))}"
            for (virus, _), names in by_folded.items()
            if len(names) > 1
        )
        if collisions:
            logger.warning(
                "%d viral protein names differ only in case: %s",
                len(collisions),
                "; ".join(collisions),
            )
        spread = sorted(
            f"{identity} {min(lengths)}-{max(lengths)}"
            for identity, draft in self.drafts.items()
            for lengths in ([stop - start + 1 for _, start, stop in draft.sites],)
            if min(lengths) < LENGTH_SPREAD * max(lengths)
        )
        if spread:
            logger.warning(
                "%d grouped viral proteins have members differing in length by "
                "more than half: %s",
                len(spread),
                ", ".join(spread),
            )


@dataclass(frozen=True, slots=True)
class _Function:
    text: str
    pmids: tuple[str, ...]


def _functions(viral: ViralPaths, sites: set[Site]) -> dict[Site, _Function]:
    """`functions.tsv`, by entry and span. A row naming a span the export does
    not have means the file no longer matches the export beside it."""
    if not viral.functions.exists():
        logger.warning(
            "%s does not exist: viral proteins will have no function text. "
            "Run bpgraph-functions",
            viral.functions,
        )
        return {}
    texts: dict[Site, _Function] = {}
    for cursor, row in rows(viral.functions):
        site = (
            required(cursor, row, "accession"),
            integer(cursor, row, "start"),
            integer(cursor, row, "stop"),
        )
        if site in texts:
            raise cursor.fail(f"{site} appears twice")
        if site not in sites:
            raise cursor.fail(
                f"{site} is not in the export: the file no longer matches it, "
                "so fetch it again"
            )
        texts[site] = _Function(
            required(cursor, row, "function"), listed(cursor, row, "pmids")
        )
    return texts


def _pooled(
    drafts: Mapping[str, _ProteinDraft], texts: Mapping[Site, _Function]
) -> dict[str, _Function]:
    """One function text per protein: the commonest over its entries and
    spans, weighted by how many rows saw each; its pmids are those of every
    span carrying that text. The proteins whose entries disagree are logged."""
    pooled: dict[str, _Function] = {}
    disagreeing: list[str] = []
    for identity, draft in drafts.items():
        weights: Counter[str] = Counter()
        pmids: dict[str, list[str]] = {}
        for site, count in draft.sites.items():
            function = texts.get(site)
            if function is None:
                continue
            weights[function.text] += count
            pmids.setdefault(function.text, []).extend(function.pmids)
        if not weights:
            continue
        if len(weights) > 1:
            disagreeing.append(identity)
        (text, _), *_ = weights.most_common()
        pooled[identity] = _Function(text, tuple(dict.fromkeys(pmids[text])))
    if disagreeing:
        logger.warning(
            "%d proteins carry different function text on different entries; "
            "each keeps the commonest: %s",
            len(disagreeing),
            ", ".join(sorted(disagreeing)),
        )
    return pooled


def _sequences(viral: ViralPaths) -> dict[str, str]:
    if not viral.entries.exists():
        logger.warning(
            "%s does not exist: the viral vault will have no sequences. "
            "Run bpgraph-functions",
            viral.entries,
        )
        return {}
    return {
        required(cursor, row, "accession"): required(cursor, row, "sequence")
        for cursor, row in rows(viral.entries)
    }


def _peptides(
    row: ExportRow,
    partners: Sequence[tuple[Mention, ProteinRef]],
    references: Iterable[PeptideReference],
) -> tuple[ReportedPeptide, ...]:
    """A description's peptides, each matched to the partner it came from, once
    per sequence and source."""
    unique: dict[tuple[str, str], ReportedPeptide] = {}
    for reference in references:
        source = next((p for m, p in partners if reference.names(m.kind, m.site)), None)
        if source is None:
            accession, start, stop = reference.site
            raise reference.cursor.fail(
                f"source {accession}:{start}-{stop} is not a partner of {row.stable_id}"
            )
        unique.setdefault(
            (reference.sequence, source.id),
            make(
                reference.cursor,
                ReportedPeptide,
                peptide=make(reference.cursor, Peptide, sequence=reference.sequence),
                source=source,
            ),
        )
    return tuple(unique.values())


def load_viral(
    viral: ViralPaths,
    curated: Sequence[ExportRow],
    references: Mapping[str, list[PeptideReference]],
    hosts: Mapping[str, Protein],
    taxonomy: Taxonomy,
    viruses: CuratedViruses,
) -> ViralSilo:
    """Load our VH rows against the host proteins they probe."""
    registry = _Registry(taxonomy=taxonomy, curated=viruses)
    kept: list[ExportRow] = []
    dropped: Counter[str] = Counter()
    unknown: set[str] = set()
    for row in curated:
        if row.psimi_id == ROOT:
            dropped[f"coded {ROOT}"] += 1
        elif row.first.accession not in hosts:
            unknown.add(row.first.accession)
            dropped["host partner not in swiss-prot"] += 1
        else:
            kept.append(row)
            registry.observe(row.cursor, row.second)
    for reason, count in dropped.items():
        logger.warning("VH: dropped %d curated rows: %s", count, reason)
    if unknown:
        logger.warning(
            "VH: %d host accessions are not in Swiss-Prot: %s",
            len(unknown),
            ", ".join(sorted(unknown)),
        )
    if registry.uncurated:
        viruses.require(registry.uncurated)
    registry.report()

    texts = _functions(viral, {row.second.site for row in curated})
    pooled = _pooled(registry.drafts, texts)
    proteins = {
        identity: make(
            draft.cursor,
            Protein,
            id=identity,
            kind=ProteinKind.VIRAL,
            name=_majority(draft.names),
            description=_majority(draft.descriptions),
            function=pooled[identity].text if identity in pooled else "",
        )
        for identity, draft in registry.drafts.items()
    }
    refs = {i: ProteinRef(id=i, kind=ProteinKind.VIRAL) for i in proteins}

    descriptions: list[Description] = []
    for row in kept:
        host = hosts[row.first.accession]
        partners = (
            (row.first, ProteinRef(id=host.id, kind=host.kind)),
            (row.second, refs[registry.identity(row.cursor, row.second)]),
        )
        descriptions.append(
            make(
                row.cursor,
                Description,
                id=row.stable_id,
                stable_ids=(row.stable_id,),
                partner_1=partners[0][1],
                partner_2=partners[1][1],
                pmid=row.pmid,
                psimi_id=row.psimi_id,
                peptides=_peptides(row, partners, references.get(row.stable_id, ())),
            )
        )

    used = {draft.virus for draft in registry.drafts.values()}
    sequences = _sequences(viral)
    return ViralSilo(
        proteins=proteins,
        viruses=tuple(v for v in viruses.viruses.values() if v.taxon_id in used),
        memberships=tuple(
            Membership(protein=refs[identity], taxon_id=draft.virus)
            for identity, draft in registry.drafts.items()
        ),
        citations=tuple(
            FunctionCitation(protein=refs[identity], pmid=pmid)
            for identity, function in pooled.items()
            for pmid in function.pmids
        ),
        descriptions=tuple(descriptions),
        vault=ViralVault(
            name=viral.vault,
            entries=tuple(
                ViralEntry(
                    accession=accession,
                    taxon_id=entry.taxon_id,
                    taxon_name=entry.taxon_name,
                    description=_majority(entry.descriptions),
                    sequence=sequences.get(accession, ""),
                )
                for accession, entry in sorted(registry.entries.items())
            ),
            mature=tuple(
                Mature(identity, accession, start, stop)
                for identity, draft in sorted(registry.drafts.items())
                for accession, start, stop in sorted(draft.sites)
            ),
            observations={row.stable_id: row.second.accession for row in kept},
        ),
        stable_ids=frozenset(row.stable_id for row in curated),
    )


def viral_pmids(run: Run) -> set[str]:
    """Every pmid the viral silo cites: our VH rows, and the function text of
    the viral proteins."""
    pmids = export_pmids(run.export, InteractionKind.VH)
    if run.viral.functions.exists():
        pmids |= {
            pmid
            for cursor, row in rows(run.viral.functions)
            for pmid in listed(cursor, row, "pmids")
        }
    return pmids
