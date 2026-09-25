"""Reading a directory of TSV files exported from the relational database.

The format is documented in docs/export.md. Three files carry the export:
`descriptions.tsv` holds one row per observation and restates, inline,
everything that row names — both partners with their coordinates, names and
taxa, and the detection method; `publications.tsv` holds one row per
publication; `peptides.tsv` holds the peptides a description reports.

There is no protein table and no method table. A protein is whatever the
description rows say it is, so `descriptions.tsv` is read twice: the first pass
reconciles the restated columns into one entry per accession, one protein per
id and one method per PSI-MI id, and the second builds the descriptions against
them. A viral protein's id is its curated virus and its name, so the first pass
is also where every viral taxon must find its virus in `curation/viruses.tsv`,
and where every entry and span a protein was seen on is gathered.

Human or viral is not a column either. It follows from `type` and the slot: a
`vh` row's second partner is the viral one, and every other partner is human.

Neither `Protein.function` nor GO has a column: the relational database holds
neither. `bpgraph.uniprot` fetches the function text and `bpgraph.go` the GO
trio into the run directory, beside `export/` rather than in it, since they are
this repo's files and not the export's — parsed here all the same, since they
are TSV in the shape docs/export.md specifies. So are the curated topic lists
in `topics/`, resolved against this export by hand.
"""

import csv
import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from bpgraph.enums import GoNamespace, GoRelation, InteractionKind, ProteinKind
from bpgraph.ids import human_protein_id, viral_protein_id
from bpgraph.models import (
    Description,
    Entry,
    Export,
    GoAnnotation,
    GoEdge,
    GoTerm,
    Involvement,
    Location,
    Membership,
    Method,
    Partner,
    Peptide,
    Protein,
    Publication,
    ReportedPeptide,
    Topic,
    Virus,
)
from bpgraph.run import GoPaths, Run
from bpgraph.taxonomy import Taxonomy, TaxonomyUnavailable
from bpgraph.viruses import CuratedViruses

logger = logging.getLogger(__name__)

DESCRIPTIONS = "descriptions.tsv"
PUBLICATIONS = "publications.tsv"
PEPTIDES = "peptides.tsv"

REQUIRED = (DESCRIPTIONS, PUBLICATIONS)

AUTHOR_SEPARATOR = ";"
TRUTHY = frozenset({"true", "t", "yes", "y", "1"})
FALSY = frozenset({"false", "f", "no", "n", "0", ""})

INTERACTION_KINDS: Mapping[str, InteractionKind] = {
    "hh": InteractionKind.HH,
    "vh": InteractionKind.VH,
}
"""The `type` column. Lowercase in the export, a node label in the graph."""

HUMAN_START = 1
"""A human protein is a full-length chain, so its coordinates start at 1."""

LENGTH_SPREAD = 0.5
"""A grouped viral protein whose shortest member is under half its longest is
reported: those members may not be one chain, and may not share one function."""


class ExportError(ValueError):
    """The export is missing something, or holds something it should not."""


@dataclass(frozen=True, slots=True)
class _Cursor:
    """Where we are, so every error names a file and a line."""

    path: Path
    line: int

    def fail(self, message: str) -> ExportError:
        return ExportError(f"{self.path.name}:{self.line}: {message}")


def _rows(path: Path) -> Iterator[tuple[_Cursor, Mapping[str, str]]]:
    """Yield the rows of one file, or nothing at all if it is absent.

    One line is one row and a tab is always a separator: quoting is off, so a
    double quote in an abstract is text like any other. What that costs is a
    cell holding a tab or a newline of its own, which no longer parses — it is
    caught here, by the line, rather than silently swallowing the rows around
    it. Free text goes into the export with both stripped out.
    """
    if not path.exists():
        if path.name in REQUIRED:
            raise ExportError(f"{path.name} is required and missing from {path.parent}")
        return
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader, None)
        if header is None:
            raise ExportError(f"{path.name} has no header row")
        columns = [column.strip() for column in header]
        for offset, values in enumerate(reader, start=2):
            if not values:
                continue
            cursor = _Cursor(path, offset)
            if len(values) != len(columns):
                raise cursor.fail(
                    f"{len(values)} columns, not {len(columns)}: a cell holds a tab "
                    "or a newline of its own"
                )
            yield (
                cursor,
                {
                    column: value.strip()
                    for column, value in zip(columns, values, strict=True)
                },
            )


def _text(cursor: _Cursor, row: Mapping[str, str], column: str) -> str:
    if column not in row:
        raise cursor.fail(f"missing column {column!r}")
    return row[column]


def _required(cursor: _Cursor, row: Mapping[str, str], column: str) -> str:
    value = _text(cursor, row, column)
    if not value:
        raise cursor.fail(f"{column} is empty")
    return value


def _integer(cursor: _Cursor, row: Mapping[str, str], column: str) -> int:
    value = _required(cursor, row, column)
    try:
        return int(value)
    except ValueError:
        raise cursor.fail(f"{column} is not a whole number: {value!r}") from None


def _boolean(cursor: _Cursor, row: Mapping[str, str], column: str) -> bool:
    value = _text(cursor, row, column).lower()
    if value in TRUTHY:
        return True
    if value in FALSY:
        return False
    raise cursor.fail(f"{column} is not a true/false value: {value!r}")


def _choice[T: StrEnum](
    cursor: _Cursor, row: Mapping[str, str], column: str, options: type[T]
) -> T:
    value = _required(cursor, row, column)
    try:
        return options(value)
    except ValueError:
        allowed = ", ".join(sorted(member.value for member in options))
        raise cursor.fail(f"{column} must be one of {allowed}, not {value!r}") from None


def _make[T: BaseModel](cursor: _Cursor, model: type[T], **fields: object) -> T:
    """Build a model, turning a validation failure into a located error.

    The models carry the rules a single row can break; this is what attaches a
    file and a line number to them, so an export is fixable by looking at it.
    """
    try:
        return model(**fields)
    except ValidationError as error:
        raise cursor.fail("; ".join(_describe(p) for p in error.errors())) from None


def _describe(problem: ErrorDetails) -> str:
    """One pydantic problem, as a line someone editing a spreadsheet can act on."""
    column = ".".join(str(part) for part in problem["loc"])
    message = problem["msg"].removeprefix("Value error, ")
    return f"{column}: {message}" if column else message


type _Site = tuple[str, int, int]
"""Where a mention sits: accession, start, stop."""


@dataclass(frozen=True, slots=True)
class _Mention:
    """One partner as one description row names it, before reconciliation."""

    accession: str
    start: int
    stop: int
    kind: ProteinKind
    name: str
    description: str
    taxon_id: int

    @property
    def site(self) -> _Site:
        return (self.accession, self.start, self.stop)


def _interaction_kind(cursor: _Cursor, row: Mapping[str, str]) -> InteractionKind:
    value = _required(cursor, row, "type")
    kind = INTERACTION_KINDS.get(value)
    if kind is None:
        allowed = ", ".join(sorted(INTERACTION_KINDS))
        raise cursor.fail(f"type must be one of {allowed}, not {value!r}")
    return kind


def _mention(
    cursor: _Cursor, row: Mapping[str, str], slot: str, kind: ProteinKind
) -> _Mention:
    start = _integer(cursor, row, f"start{slot}")
    accession = _required(cursor, row, f"accession{slot}")
    if kind is ProteinKind.HUMAN and start != HUMAN_START:
        raise cursor.fail(
            f"human protein {accession} starts at {start}: a human protein is a "
            "full-length chain"
        )
    return _Mention(
        accession=accession,
        start=start,
        stop=_integer(cursor, row, f"stop{slot}"),
        kind=kind,
        name=_required(cursor, row, f"name{slot}"),
        description=_text(cursor, row, f"description{slot}"),
        taxon_id=_integer(cursor, row, f"ncbi_taxon_id{slot}"),
    )


def _mentions(cursor: _Cursor, row: Mapping[str, str]) -> tuple[_Mention, _Mention]:
    """The two proteins a description row names.

    Which of them is viral is not a column: a `vh` row's second partner is the
    viral one, and every other partner is human.
    """
    second = (
        ProteinKind.VIRAL
        if _interaction_kind(cursor, row) is InteractionKind.VH
        else ProteinKind.HUMAN
    )
    return (
        _mention(cursor, row, "1", ProteinKind.HUMAN),
        _mention(cursor, row, "2", second),
    )


@dataclass(slots=True)
class _EntryDraft:
    """Every mention of one accession."""

    cursor: _Cursor
    taxon_id: int
    taxon_name: str
    descriptions: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class _ProteinDraft:
    """Every mention of one protein, gathered before a node is made of it.

    A protein has no table of its own, so it is described once per description
    row it takes part in — hundreds of times over, across strains and entries,
    and not always identically. The counters are what decides between the
    variants, and `sites` is how often each entry and span carried it.
    """

    cursor: _Cursor
    kind: ProteinKind
    names: Counter[str] = field(default_factory=Counter)
    descriptions: Counter[str] = field(default_factory=Counter)
    sites: Counter[_Site] = field(default_factory=Counter)


def _widest(identity: str, spans: Iterable[tuple[int, int]]) -> tuple[int, int]:
    """The longest span a human entry was exported with.

    Two UniProt releases disagreeing about a sequence's length land on one
    entry, and the longer wins, on the assumption that it is the later.
    """
    distinct = sorted(set(spans))
    widest = max(distinct, key=lambda span: span[1] - span[0])
    if len(distinct) > 1:
        seen = ", ".join(f"{start}-{stop}" for start, stop in distinct)
        logger.warning("%s was exported as %s; keeping %s-%s", identity, seen, *widest)
    return widest


def _majority(identity: str, column: str, values: Counter[str]) -> str:
    """The commonest value a column held for one protein or entry.

    Every description row restates a protein's name and description, and a few
    disagree — a gene renamed after some of the rows were written. The majority
    is the current name; the rest are stale.
    """
    (value, _), *rest = values.most_common()
    if rest:
        seen = ", ".join(
            f"{other!r} ({count})" for other, count in values.most_common()
        )
        logger.debug("%s: %s is given as %s; keeping %r", identity, column, seen, value)
    return value


@dataclass(slots=True)
class _Registry:
    """The protein and entry tables, rebuilt from `descriptions.tsv`.

    A human protein is its accession. A viral one is its curated virus and its
    curated name, so every strain's copy of `HBx` lands on one draft, and the
    entries and spans it was seen on are what `:ON_ENTRY` records.
    """

    taxonomy: Taxonomy
    curated: CuratedViruses
    kinds: dict[str, ProteinKind] = field(default_factory=dict)
    entries: dict[str, _EntryDraft] = field(default_factory=dict)
    drafts: dict[str, _ProteinDraft] = field(default_factory=dict)
    taxa: dict[int, tuple[int, str]] = field(default_factory=dict)
    viruses: dict[int, Virus | None] = field(default_factory=dict)
    virus_of: dict[str, int] = field(default_factory=dict)
    """Each viral protein's curated virus, by taxon id."""
    uncurated: set[int] = field(default_factory=set)

    def observe(self, cursor: _Cursor, mention: _Mention) -> None:
        declared = self.kinds.setdefault(mention.accession, mention.kind)
        if declared is not mention.kind:
            raise cursor.fail(
                f"{mention.accession} is {declared.name.lower()} elsewhere and "
                f"{mention.kind.name.lower()} here"
            )
        taxon_id, taxon_name = self._taxon(cursor, mention.taxon_id)
        entry = self.entries.get(mention.accession)
        if entry is None:
            entry = _EntryDraft(cursor=cursor, taxon_id=taxon_id, taxon_name=taxon_name)
            self.entries[mention.accession] = entry
        elif entry.taxon_id != taxon_id:
            raise cursor.fail(
                f"{mention.accession} is taxon {entry.taxon_id} elsewhere and "
                f"{mention.taxon_id} here"
            )
        entry.descriptions[mention.description] += 1

        virus = self._virus(taxon_id) if mention.kind is ProteinKind.VIRAL else None
        if mention.kind is ProteinKind.VIRAL and virus is None:
            self.uncurated.add(taxon_id)
            return
        identity = self.identity(cursor, mention)
        draft = self.drafts.get(identity)
        if draft is None:
            draft = _ProteinDraft(cursor=cursor, kind=mention.kind)
            self.drafts[identity] = draft
            if virus is not None:
                self.virus_of[identity] = virus.taxon_id
        draft.names[mention.name] += 1
        draft.descriptions[mention.description] += 1
        draft.sites[mention.site] += 1

    def identity(self, cursor: _Cursor, mention: _Mention) -> str:
        """The id of the protein a mention names."""
        if mention.kind is ProteinKind.HUMAN:
            return human_protein_id(mention.accession)
        virus = self._virus(self._taxon(cursor, mention.taxon_id)[0])
        if virus is None:
            raise cursor.fail(f"taxon {mention.taxon_id} has no curated virus")
        return viral_protein_id(virus.taxon_id, mention.name)

    def _taxon(self, cursor: _Cursor, taxon_id: int) -> tuple[int, str]:
        """Canonicalize a taxon id and name it from the local taxonomy.

        The export carries whatever id was recorded at curation time; NCBI
        retires ids as it reorganizes, so this is where a legacy one becomes
        the current one and the graph only ever holds names NCBI still uses.
        Memoized — a thousand distinct taxa are restated across 400,000 rows.
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

    def require_curated(self) -> None:
        """The build gate: every viral taxon belongs to a curated virus."""
        if self.uncurated:
            self.curated.require(self.uncurated)

    def proteins(self) -> dict[str, Protein]:
        return {
            identity: _make(
                draft.cursor,
                Protein,
                id=identity,
                kind=draft.kind,
                name=_majority(identity, "name", draft.names),
                description=_majority(identity, "description", draft.descriptions),
            )
            for identity, draft in self.drafts.items()
        }

    def entry_models(self) -> tuple[Entry, ...]:
        return tuple(
            _make(
                entry.cursor,
                Entry,
                accession=accession,
                taxon_id=entry.taxon_id,
                taxon_name=entry.taxon_name,
                description=_majority(accession, "description", entry.descriptions),
            )
            for accession, entry in self.entries.items()
        )

    def locations(self, proteins: Mapping[str, Protein]) -> tuple[Location, ...]:
        """Every entry and span a protein was seen on. A human protein is its
        one entry, at the widest span it was exported with."""
        located: list[Location] = []
        for identity, draft in self.drafts.items():
            protein = proteins[identity]
            if draft.kind is ProteinKind.HUMAN:
                start, stop = _widest(
                    identity, ((start, stop) for _, start, stop in draft.sites)
                )
                sites: Iterable[_Site] = ((identity, start, stop),)
            else:
                sites = draft.sites
            located.extend(
                _make(
                    draft.cursor,
                    Location,
                    protein=protein,
                    accession=accession,
                    start=start,
                    stop=stop,
                )
                for accession, start, stop in sites
            )
        return tuple(located)

    def memberships(self, proteins: Mapping[str, Protein]) -> tuple[Membership, ...]:
        return tuple(
            Membership(protein=proteins[identity], taxon_id=virus)
            for identity, virus in self.virus_of.items()
        )

    def used_viruses(self) -> tuple[Virus, ...]:
        used = set(self.virus_of.values())
        return tuple(
            virus for virus in self.curated.viruses.values() if virus.taxon_id in used
        )

    def report(self) -> None:
        """The checks a human should look at, none of which stops a build.

        Names are case-sensitive, so names differing only in case are two
        proteins — genuinely so for EBV's `BARF1` and `BaRF1`, but any new pair
        is worth a look. And the entries of one grouped protein should be one
        chain: members whose lengths differ by more than half are listed.
        """
        by_folded: dict[tuple[int, str], set[str]] = {}
        for identity, virus in self.virus_of.items():
            (name, _), *_ = self.drafts[identity].names.most_common()
            by_folded.setdefault((virus, name.lower()), set()).add(name)
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
        spread: list[str] = []
        for identity, draft in self.drafts.items():
            if draft.kind is not ProteinKind.VIRAL:
                continue
            lengths = [stop - start + 1 for _, start, stop in draft.sites]
            if min(lengths) < LENGTH_SPREAD * max(lengths):
                spread.append(f"{identity} {min(lengths)}-{max(lengths)}")
        if spread:
            logger.warning(
                "%d grouped viral proteins have members differing in length by "
                "more than half: %s",
                len(spread),
                ", ".join(sorted(spread)),
            )


@dataclass(frozen=True, slots=True)
class _PeptideReference:
    """A `peptides.tsv` row, before its source is matched to a partner.

    The row names the source in full — kind, accession and span — so it is
    matched against where each of the description's two partners was seen. A
    human partner is its whole entry, so there the accession alone decides.
    """

    cursor: _Cursor
    sequence: str
    kind: ProteinKind
    site: _Site

    def names(self, mention: _Mention) -> bool:
        if self.kind is not mention.kind:
            return False
        if self.kind is ProteinKind.HUMAN:
            return self.site[0] == mention.accession
        return self.site == mention.site


def _reported(
    reference: _PeptideReference, partners: Sequence[tuple[_Mention, Protein]]
) -> ReportedPeptide:
    """Match a peptide's source to one of its description's partners.

    Naming anything else is an export bug, caught here with the peptide row's
    own line number.
    """
    source = next((p for m, p in partners if reference.names(m)), None)
    if source is None:
        accession, start, stop = reference.site
        raise reference.cursor.fail(
            f"source {accession}:{start}-{stop} is not a partner of this description"
        )
    return _make(
        reference.cursor,
        ReportedPeptide,
        peptide=_make(reference.cursor, Peptide, sequence=reference.sequence),
        source=source,
    )


def _resolve_human(
    cursor: _Cursor, humans: Mapping[str, Protein], row: Mapping[str, str]
) -> Protein:
    """GO annotations name a human protein by accession alone, which
    identifies exactly one node."""
    accession = _required(cursor, row, "accession")
    protein = humans.get(human_protein_id(accession))
    if protein is None:
        raise cursor.fail(f"{accession} is not a human protein in {DESCRIPTIONS}")
    return protein


def _collapse(reported: Iterator[ReportedPeptide]) -> tuple[ReportedPeptide, ...]:
    """One entry per sequence and source, in the order first seen.

    A description naming the same peptide from the same partner twice is saying
    one thing twice, and one `:REPORTS` edge is what it means.
    """
    unique: dict[tuple[str, str], ReportedPeptide] = {}
    for entry in reported:
        unique.setdefault((entry.peptide.sequence, entry.source.id), entry)
    return tuple(unique.values())


@dataclass(frozen=True, slots=True)
class TsvExport:
    """Reads one run directory. See docs/export.md for the file list."""

    run: Run
    taxonomy: Taxonomy
    curated: CuratedViruses

    @classmethod
    def open(cls, directory: Path) -> Self:
        """Read `directory` against the taxonomy fetched into it and the
        curated virus list."""
        run = Run(directory)
        taxonomy = Taxonomy.open(run.taxonomy)
        return cls(run, taxonomy, CuratedViruses.load(taxonomy))

    def load(self) -> Export:
        publications = self._publications()
        registry, methods = self._scan()
        proteins = registry.proteins()
        self._enrich(registry, proteins)
        viruses = registry.used_viruses()
        families, taxon_links = self.taxonomy.families(v.taxon_id for v in viruses)
        humans = {
            protein.id: protein
            for protein in proteins.values()
            if protein.kind is ProteinKind.HUMAN
        }
        involvements = tuple(self._involvements(humans))
        go = self._go()
        go_terms = tuple(self._go_terms(go))
        known = frozenset(term.go_id for term in go_terms)
        return Export(
            proteins=tuple(proteins.values()),
            entries=registry.entry_models(),
            locations=registry.locations(proteins),
            viruses=viruses,
            families=families,
            taxon_links=taxon_links,
            memberships=registry.memberships(proteins),
            topics=tuple(
                Topic(name=name) for name in sorted({i.topic for i in involvements})
            ),
            involvements=involvements,
            publications=tuple(publications.values()),
            methods=methods,
            descriptions=self._descriptions(registry, proteins, publications),
            go_terms=go_terms,
            go_edges=tuple(self._go_edges(go, known)),
            go_annotations=tuple(self._go_annotations(go, known, humans)),
        )

    def _scan(self) -> tuple[_Registry, tuple[Method, ...]]:
        """First pass over `descriptions.tsv`: the entities it restates inline."""
        registry = _Registry(taxonomy=self.taxonomy, curated=self.curated)
        methods: dict[str, Method] = {}
        for cursor, row in _rows(self.run.export / DESCRIPTIONS):
            for mention in _mentions(cursor, row):
                registry.observe(cursor, mention)
            method = _make(
                cursor,
                Method,
                psimi_id=_required(cursor, row, "psimi_id"),
                name=_required(cursor, row, "method"),
            )
            known = methods.setdefault(method.psimi_id, method)
            if known != method:
                raise cursor.fail(
                    f"{method.psimi_id} is {known.name!r} elsewhere and "
                    f"{method.name!r} here"
                )
        registry.require_curated()
        registry.report()
        return registry, tuple(methods.values())

    def _descriptions(
        self,
        registry: _Registry,
        proteins: Mapping[str, Protein],
        publications: Mapping[str, Publication],
    ) -> tuple[Description, ...]:
        """Second pass: the observations themselves, against the first pass."""
        peptides = self._peptides()
        descriptions: list[Description] = []
        seen: set[str] = set()
        for cursor, row in _rows(self.run.export / DESCRIPTIONS):
            stable_id = _required(cursor, row, "stable_id")
            if stable_id in seen:
                raise cursor.fail(f"stable_id {stable_id!r} appears twice")
            seen.add(stable_id)
            pmid = _required(cursor, row, "pmid")
            if pmid not in publications:
                raise cursor.fail(f"pmid {pmid} is not in {PUBLICATIONS}")
            partners = [
                (mention, proteins[registry.identity(cursor, mention)])
                for mention in _mentions(cursor, row)
            ]
            (first_mention, first), (second_mention, second) = partners
            descriptions.append(
                _make(
                    cursor,
                    Description,
                    stable_id=stable_id,
                    partner_1=Partner(protein=first, accession=first_mention.accession),
                    partner_2=Partner(
                        protein=second, accession=second_mention.accession
                    ),
                    pmid=pmid,
                    psimi_id=_required(cursor, row, "psimi_id"),
                    peptides=_collapse(
                        _reported(reference, partners)
                        for reference in peptides.get(stable_id, ())
                    ),
                )
            )
        unknown = set(peptides) - seen
        if unknown:
            raise ExportError(
                f"{PEPTIDES} references descriptions absent from {DESCRIPTIONS}: "
                f"{', '.join(sorted(unknown))}"
            )
        return tuple(descriptions)

    def _peptides(self) -> dict[str, list[_PeptideReference]]:
        """Group the rows by description. Their source is resolved later,
        against the two partners of the description they belong to."""
        grouped: dict[str, list[_PeptideReference]] = {}
        for cursor, row in _rows(self.run.export / PEPTIDES):
            reference = _PeptideReference(
                cursor=cursor,
                sequence=_required(cursor, row, "sequence").upper(),
                kind=_choice(cursor, row, "source_type", ProteinKind),
                site=(
                    _required(cursor, row, "source_accession"),
                    _integer(cursor, row, "source_start"),
                    _integer(cursor, row, "source_stop"),
                ),
            )
            grouped.setdefault(_required(cursor, row, "stable_id"), []).append(
                reference
            )
        return grouped

    def _enrich(self, registry: _Registry, proteins: dict[str, Protein]) -> None:
        """Attach the UniProt function text fetched for this export.

        The file holds one text per entry and span, and a viral protein seen on
        several entries gets several. Curation groups one chain across strains,
        so they should agree; the text the protein takes is the commonest,
        weighted by how many description rows saw each entry and span, and the
        proteins whose entries disagree are logged.

        No file at all means the fetch has not been run for this export — a
        whole stage missing, worth a line in the log; a row naming a span this
        export does not have means the file no longer matches the export beside
        it, and the fix for both is the same command.
        """
        path = self.run.functions
        if not path.exists():
            logger.warning(
                "%s does not exist: proteins will have no function text. "
                "Run bpgraph-functions %s",
                path,
                self.run.directory,
            )
            return
        texts: dict[tuple[ProteinKind, _Site], str] = {}
        for cursor, row in _rows(path):
            kind = _choice(cursor, row, "type", ProteinKind)
            site = (
                _required(cursor, row, "accession"),
                _integer(cursor, row, "start"),
                _integer(cursor, row, "stop"),
            )
            if (kind, site) in texts:
                raise cursor.fail(f"{site} appears twice")
            texts[(kind, site)] = _required(cursor, row, "function")

        located: set[tuple[ProteinKind, _Site]] = set()
        disagreeing: list[str] = []
        for identity, draft in registry.drafts.items():
            weights: Counter[str] = Counter()
            for site, count in draft.sites.items():
                located.add((draft.kind, site))
                text = texts.get((draft.kind, site))
                if text:
                    weights[text] += count
            if not weights:
                continue
            if len(weights) > 1:
                disagreeing.append(identity)
            (function, _), *_ = weights.most_common()
            proteins[identity] = proteins[identity].model_copy(
                update={"function": function}
            )

        stale = set(texts) - located
        if stale:
            raise ExportError(
                f"{path.name} names {len(stale)} spans not in {DESCRIPTIONS}, e.g. "
                f"{sorted(stale)[0][1]}: it no longer matches {self.run.directory}, "
                "so fetch it again"
            )
        if disagreeing:
            logger.warning(
                "%d proteins carry different function text on different entries; "
                "each keeps the commonest: %s",
                len(disagreeing),
                ", ".join(sorted(disagreeing)),
            )

    def _involvements(self, humans: Mapping[str, Protein]) -> Iterator[Involvement]:
        """Every topic list in the run's `topics/`, one topic per file.

        A list may name a gene with no interaction in this export: it is not a
        protein here, so it is logged and left out rather than failing the run.
        """
        for path in sorted(self.run.topics.glob("*.tsv")):
            absent: list[str] = []
            for cursor, row in _rows(path):
                accession = _required(cursor, row, "accession")
                protein = humans.get(accession)
                if protein is None:
                    absent.append(accession)
                    continue
                yield _make(
                    cursor,
                    Involvement,
                    protein=protein,
                    topic=path.stem,
                    properties={k: v for k, v in row.items() if k != "accession"},
                )
            if absent:
                logger.warning(
                    "%s: %d accessions are not human proteins in %s: %s",
                    path.name,
                    len(absent),
                    DESCRIPTIONS,
                    ", ".join(absent),
                )

    def _publications(self) -> dict[str, Publication]:
        publications: dict[str, Publication] = {}
        for cursor, row in _rows(self.run.export / PUBLICATIONS):
            authors = _text(cursor, row, "authors")
            publication = _make(
                cursor,
                Publication,
                pmid=_required(cursor, row, "pmid"),
                title=_required(cursor, row, "title"),
                year=_integer(cursor, row, "year"),
                journal=_text(cursor, row, "journal"),
                abstract=_text(cursor, row, "abstract"),
                authors=tuple(
                    author.strip()
                    for author in authors.split(AUTHOR_SEPARATOR)
                    if author.strip()
                ),
            )
            if publication.pmid in publications:
                raise cursor.fail(f"pmid {publication.pmid} appears twice")
            publications[publication.pmid] = publication
        return publications

    def _go(self) -> GoPaths:
        """Where this export's GO trio lives, having checked it is all there.

        The three files are written by one command against one ontology
        release, so none of them means anything without the others: an edge
        names two terms and an annotation names one. All three missing is a
        run that skipped the fetch, which loads without GO and says so; some of
        them missing is a set that has been taken apart, and the fix is to
        fetch it again rather than to build half of it.
        """
        paths = self.run.go
        missing = paths.missing
        if len(missing) == len(paths.paths):
            logger.warning(
                "%s does not exist: the graph will have no GO terms. Run bpgraph-go %s",
                paths.terms,
                self.run.directory,
            )
        elif missing:
            raise ExportError(
                f"{', '.join(path.name for path in missing)} missing beside "
                f"{paths.terms.name}: the GO files are written together, so "
                f"fetch them again with bpgraph-go {self.run.directory}"
            )
        return paths

    def _go_terms(self, paths: GoPaths) -> Iterator[GoTerm]:
        for cursor, row in _rows(paths.terms):
            yield _make(
                cursor,
                GoTerm,
                go_id=_required(cursor, row, "go_id"),
                name=_required(cursor, row, "name"),
                namespace=_choice(cursor, row, "namespace", GoNamespace),
                obsolete=_boolean(cursor, row, "obsolete"),
            )

    def _go_edges(self, paths: GoPaths, known: frozenset[str]) -> Iterator[GoEdge]:
        """The ontology above the annotated terms.

        Both ends must be terms this export carries. A write resolves an edge
        by matching its two nodes, so an end that is not there is not an error
        in the graph — it is an edge that quietly never appears, and with it a
        rollup that stops short.
        """
        for cursor, row in _rows(paths.edges):
            edge = _make(
                cursor,
                GoEdge,
                child_go_id=_required(cursor, row, "child_go_id"),
                parent_go_id=_required(cursor, row, "parent_go_id"),
                relation=_choice(cursor, row, "relation", GoRelation),
            )
            for go_id in (edge.child_go_id, edge.parent_go_id):
                if go_id not in known:
                    raise cursor.fail(f"{go_id} is not in {paths.terms.name}")
            yield edge

    def _go_annotations(
        self, paths: GoPaths, known: frozenset[str], humans: Mapping[str, Protein]
    ) -> Iterator[GoAnnotation]:
        """What the proteins are annotated with. Human only: GO annotates a
        whole accession, and a viral protein here is one chain of one."""
        for cursor, row in _rows(paths.annotations):
            annotation = _make(
                cursor,
                GoAnnotation,
                protein=_resolve_human(cursor, humans, row),
                go_id=_required(cursor, row, "go_id"),
                evidence_code=_required(cursor, row, "evidence_code"),
                assigned_by=_text(cursor, row, "assigned_by"),
                qualifier=_text(cursor, row, "qualifier"),
            )
            if annotation.go_id not in known:
                raise cursor.fail(f"{annotation.go_id} is not in {paths.terms.name}")
            yield annotation
