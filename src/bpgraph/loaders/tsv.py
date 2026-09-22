"""Reading a directory of TSV files exported from the relational database.

The format is documented in docs/export.md. Three files carry the export:
`descriptions.tsv` holds one row per observation and restates, inline,
everything that row names — both partners with their coordinates, names and
taxa, and the detection method; `publications.tsv` holds one row per
publication; `peptides.tsv` holds the peptides a description reports.

There is no protein table and no method table. A protein is whatever the
description rows say it is, so `descriptions.tsv` is read twice: the first pass
reconciles the restated columns into one protein per id and one method per
PSI-MI id, and the second builds the descriptions against them. Two passes
rather than one because a description can only be resolved once every mention
of its partners has been seen — reconciling is what decides a protein's
coordinates.

Human or viral is not a column either. It follows from `type` and the slot: a
`vh` row's second partner is the viral one, and every other partner is human.

`Protein.function` has no column: the relational database does not hold it.
`bpgraph.uniprot` fetches it into `data/functions-<export>.tsv`, and the GO
trio will land beside it. Those files are this repo's rather than the export's,
so they sit outside the export directory and are read from `enrichment` —
parsed here all the same, since they are TSV in the shape docs/export.md
specifies.
"""

import csv
import logging
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from bpgraph.enums import GoNamespace, GoRelation, InteractionKind, ProteinKind
from bpgraph.ids import protein_id
from bpgraph.models import (
    Description,
    Export,
    GoAnnotation,
    GoEdge,
    GoTerm,
    Method,
    Peptide,
    Protein,
    ProteinSet,
    Publication,
    ReportedPeptide,
    SetMembership,
)
from bpgraph.taxonomy import Taxonomy, TaxonomyUnavailable

logger = logging.getLogger(__name__)

DATA_DIRECTORY = Path("data")

DESCRIPTIONS = "descriptions.tsv"
PUBLICATIONS = "publications.tsv"
PEPTIDES = "peptides.tsv"
MEMBERSHIPS = "memberships.tsv"
GO_TERMS = "go_terms.tsv"
GO_EDGES = "go_edges.tsv"
GO_ANNOTATIONS = "go_annotations.tsv"

REQUIRED = (DESCRIPTIONS, PUBLICATIONS)

FUNCTIONS = "functions-{}.tsv"
EXPORT_PREFIX = "graph-"

MEMBERSHIP_COLUMNS = frozenset({"set_name", "accession"})
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


class ExportError(ValueError):
    """The export is missing something, or holds something it should not."""


def functions_path(directory: Path, enrichment: Path = DATA_DIRECTORY) -> Path:
    """Where the function text fetched for one export directory lives.

    Outside that directory, because it is this repo's file rather than the
    relational database's — but named after it, so the pair is visible at a
    glance: `data/graph-2026-09-09` goes with `data/functions-2026-09-09.tsv`.
    A new export is a new directory, so it looks for a file that does not exist
    yet rather than quietly reading the last one. A directory named by some
    other convention keeps its whole name.
    """
    return enrichment / FUNCTIONS.format(directory.name.removeprefix(EXPORT_PREFIX))


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
    def id(self) -> str:
        return protein_id(self.accession, self.start, self.stop, self.kind)


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
            "full-length chain, and its id carries no coordinates"
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
class _Draft:
    """Every mention of one protein, gathered before a node is made of it.

    A protein has no table of its own, so it is described once per description
    row it takes part in — hundreds of times over, and not always identically.
    The counters are what decides between the variants.
    """

    cursor: _Cursor
    kind: ProteinKind
    accession: str
    taxon_id: int
    taxon_name: str
    spans: Counter[tuple[int, int]] = field(default_factory=Counter)
    names: Counter[str] = field(default_factory=Counter)
    descriptions: Counter[str] = field(default_factory=Counter)


def _widest(identity: str, spans: Counter[tuple[int, int]]) -> tuple[int, int]:
    """The longest span one protein was exported with.

    Only a human protein can reach here with more than one. A viral id carries
    its own coordinates, so a second span there is a second protein; a human id
    is a bare accession, so two UniProt releases disagreeing about the sequence
    length land on one node, and the later — the longer — wins.
    """
    widest = max(spans, key=lambda span: span[1] - span[0])
    if len(spans) > 1:
        seen = ", ".join(f"{start}-{stop}" for start, stop in sorted(spans))
        logger.warning("%s was exported as %s; keeping %s-%s", identity, seen, *widest)
    return widest


def _majority(identity: str, column: str, values: Counter[str]) -> str:
    """The commonest value a column held for one protein.

    Every description row restates a protein's name and description, and a few
    disagree — a gene renamed after some of the rows were written. The majority
    is the current name; the rest are stale.
    """
    (value, _), *rest = values.most_common()
    if rest:
        seen = ", ".join(
            f"{other!r} ({count})" for other, count in values.most_common()
        )
        logger.warning(
            "%s: %s is given as %s; keeping %r", identity, column, seen, value
        )
    return value


@dataclass(slots=True)
class _Registry:
    """The protein table, rebuilt from the mentions in `descriptions.tsv`.

    Keyed by derived id rather than by `(accession, start, stop)`, because that
    is the identity the graph enforces: two human rows differing only in `stop`
    are one node, and collapsing them here is what keeps the id constraint and
    the coordinates agreeing.
    """

    taxonomy: Taxonomy
    drafts: dict[str, _Draft] = field(default_factory=dict)
    kinds: dict[str, ProteinKind] = field(default_factory=dict)
    taxa: dict[int, tuple[int, str]] = field(default_factory=dict)

    def observe(self, cursor: _Cursor, mention: _Mention) -> None:
        declared = self.kinds.setdefault(mention.accession, mention.kind)
        if declared is not mention.kind:
            raise cursor.fail(
                f"{mention.accession} is {declared.name.lower()} elsewhere and "
                f"{mention.kind.name.lower()} here"
            )
        draft = self.drafts.get(mention.id)
        if draft is None:
            taxon_id, taxon_name = self._taxon(cursor, mention.taxon_id)
            draft = _Draft(
                cursor=cursor,
                kind=mention.kind,
                accession=mention.accession,
                taxon_id=taxon_id,
                taxon_name=taxon_name,
            )
            self.drafts[mention.id] = draft
        elif self._taxon(cursor, mention.taxon_id)[0] != draft.taxon_id:
            raise cursor.fail(
                f"{mention.id} is taxon {draft.taxon_id} elsewhere and "
                f"{mention.taxon_id} here"
            )
        draft.spans[(mention.start, mention.stop)] += 1
        draft.names[mention.name] += 1
        draft.descriptions[mention.description] += 1

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
        resolved = (current, self.taxonomy.get(current).name)
        self.taxa[taxon_id] = resolved
        return resolved

    def proteins(self) -> dict[str, Protein]:
        """One `:Protein` per id, with the variants reconciled."""
        return {
            identity: _reconcile(identity, draft)
            for identity, draft in self.drafts.items()
        }


def _reconcile(identity: str, draft: _Draft) -> Protein:
    """One protein out of every mention of it."""
    start, stop = _widest(identity, draft.spans)
    return _make(
        draft.cursor,
        Protein,
        accession=draft.accession,
        start=start,
        stop=stop,
        kind=draft.kind,
        name=_majority(identity, "name", draft.names),
        description=_majority(identity, "description", draft.descriptions),
        taxon_id=draft.taxon_id,
        taxon_name=draft.taxon_name,
    )


@dataclass(frozen=True, slots=True)
class _PeptideReference:
    """A `peptides.tsv` row, before its source is matched to a partner.

    The row names the source protein in full — kind, accession and span — which
    is exactly what a derived id is made of, so the match against the
    description's two partners is an id comparison.
    """

    cursor: _Cursor
    sequence: str
    source_id: str


def _reported(
    reference: _PeptideReference, partners: tuple[Protein, Protein]
) -> ReportedPeptide:
    """Match a peptide's source to one of its description's partners.

    Naming anything else is an export bug, caught here with the peptide row's
    own line number.
    """
    source = next((p for p in partners if p.id == reference.source_id), None)
    if source is None:
        raise reference.cursor.fail(
            f"source {reference.source_id} is not a partner of this description "
            f"({partners[0].id}, {partners[1].id})"
        )
    return _make(
        reference.cursor,
        ReportedPeptide,
        peptide=_make(reference.cursor, Peptide, sequence=reference.sequence),
        source=source,
    )


def _resolve(
    cursor: _Cursor, proteins: Mapping[str, Protein], mention: _Mention
) -> Protein:
    protein = proteins.get(mention.id)
    if protein is None:
        raise cursor.fail(f"{mention.id} was not seen while scanning {DESCRIPTIONS}")
    return protein


def _resolve_human(
    cursor: _Cursor, humans: Mapping[str, Protein], row: Mapping[str, str]
) -> Protein:
    """Memberships and GO annotations name a human protein by accession alone,
    which identifies exactly one node."""
    accession = _required(cursor, row, "accession")
    protein = humans.get(accession)
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
    """Reads one export directory. See docs/export.md for the file list."""

    directory: Path = DATA_DIRECTORY
    enrichment: Path = DATA_DIRECTORY
    """Where the files this repo generates live — the function text, and the GO
    trio once it exists. Deliberately not the export directory: that one holds
    what the relational database exports and nothing else, while these outlive
    any one export the way the taxonomy does."""

    taxonomy: Taxonomy = field(default_factory=Taxonomy.open)

    def load(self) -> Export:
        publications = self._publications()
        proteins, methods = self._scan()
        self._enrich(proteins)
        taxa, taxon_links = self.taxonomy.resolve(
            protein.taxon_id
            for protein in proteins.values()
            if protein.kind is ProteinKind.VIRAL
        )
        humans = {
            protein.accession: protein
            for protein in proteins.values()
            if protein.kind is ProteinKind.HUMAN
        }
        memberships = tuple(self._memberships(humans))
        return Export(
            proteins=tuple(proteins.values()),
            taxa=taxa,
            taxon_links=taxon_links,
            protein_sets=tuple(
                ProteinSet(name=name)
                for name in sorted({m.set_name for m in memberships})
            ),
            memberships=memberships,
            publications=tuple(publications.values()),
            methods=methods,
            descriptions=self._descriptions(proteins, publications),
            go_terms=tuple(self._go_terms()),
            go_edges=tuple(self._go_edges()),
            go_annotations=tuple(self._go_annotations(humans)),
        )

    def _scan(self) -> tuple[dict[str, Protein], tuple[Method, ...]]:
        """First pass over `descriptions.tsv`: the entities it restates inline."""
        registry = _Registry(taxonomy=self.taxonomy)
        methods: dict[str, Method] = {}
        for cursor, row in _rows(self.directory / DESCRIPTIONS):
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
        return registry.proteins(), tuple(methods.values())

    def _descriptions(
        self,
        proteins: Mapping[str, Protein],
        publications: Mapping[str, Publication],
    ) -> tuple[Description, ...]:
        """Second pass: the observations themselves, against the first pass."""
        peptides = self._peptides()
        descriptions: list[Description] = []
        seen: set[str] = set()
        for cursor, row in _rows(self.directory / DESCRIPTIONS):
            stable_id = _required(cursor, row, "stable_id")
            if stable_id in seen:
                raise cursor.fail(f"stable_id {stable_id!r} appears twice")
            seen.add(stable_id)
            pmid = _required(cursor, row, "pmid")
            if pmid not in publications:
                raise cursor.fail(f"pmid {pmid} is not in {PUBLICATIONS}")
            first, second = (
                _resolve(cursor, proteins, mention)
                for mention in _mentions(cursor, row)
            )
            descriptions.append(
                _make(
                    cursor,
                    Description,
                    stable_id=stable_id,
                    protein_1=first,
                    protein_2=second,
                    pmid=pmid,
                    psimi_id=_required(cursor, row, "psimi_id"),
                    peptides=_collapse(
                        _reported(reference, (first, second))
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
        for cursor, row in _rows(self.directory / PEPTIDES):
            reference = _PeptideReference(
                cursor=cursor,
                sequence=_required(cursor, row, "sequence").upper(),
                source_id=protein_id(
                    _required(cursor, row, "source_accession"),
                    _integer(cursor, row, "source_start"),
                    _integer(cursor, row, "source_stop"),
                    _choice(cursor, row, "source_type", ProteinKind),
                ),
            )
            grouped.setdefault(_required(cursor, row, "stable_id"), []).append(
                reference
            )
        return grouped

    def _enrich(self, proteins: dict[str, Protein]) -> None:
        """Attach the UniProt function text fetched for this export.

        A protein UniProt says nothing about simply has no row, and keeps the
        empty `function` it was built with. No file at all means the fetch has
        not been run for this export — a whole stage missing rather than a
        protein, so it is worth a line in the log; a row naming a protein this
        export does not have means the file no longer matches the directory it
        is named after, and the fix for both is the same command.
        """
        path = functions_path(self.directory, self.enrichment)
        if not path.exists():
            logger.warning(
                "%s does not exist: proteins will have no function text. "
                "Run bpgraph-functions %s",
                path,
                self.directory,
            )
            return
        seen: set[str] = set()
        for cursor, row in _rows(path):
            identity = protein_id(
                _required(cursor, row, "accession"),
                _integer(cursor, row, "start"),
                _integer(cursor, row, "stop"),
                _choice(cursor, row, "type", ProteinKind),
            )
            if identity in seen:
                raise cursor.fail(f"{identity} appears twice")
            seen.add(identity)
            protein = proteins.get(identity)
            if protein is None:
                raise cursor.fail(
                    f"{identity} is not in {DESCRIPTIONS}: this file no longer "
                    f"matches {self.directory}, so fetch it again"
                )
            proteins[identity] = protein.model_copy(
                update={"function": _required(cursor, row, "function")}
            )

    def _memberships(self, humans: Mapping[str, Protein]) -> Iterator[SetMembership]:
        for cursor, row in _rows(self.directory / MEMBERSHIPS):
            protein = _resolve_human(cursor, humans, row)
            attributes = {
                column: value
                for column, value in row.items()
                if column not in MEMBERSHIP_COLUMNS and value
            }
            yield _make(
                cursor,
                SetMembership,
                protein=protein,
                set_name=_required(cursor, row, "set_name"),
                attributes=attributes,
            )

    def _publications(self) -> dict[str, Publication]:
        publications: dict[str, Publication] = {}
        for cursor, row in _rows(self.directory / PUBLICATIONS):
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

    def _go_terms(self) -> Iterator[GoTerm]:
        for cursor, row in _rows(self.enrichment / GO_TERMS):
            yield _make(
                cursor,
                GoTerm,
                go_id=_required(cursor, row, "go_id"),
                name=_required(cursor, row, "name"),
                namespace=_choice(cursor, row, "namespace", GoNamespace),
                obsolete=_boolean(cursor, row, "obsolete"),
            )

    def _go_edges(self) -> Iterator[GoEdge]:
        for cursor, row in _rows(self.enrichment / GO_EDGES):
            yield _make(
                cursor,
                GoEdge,
                child_go_id=_required(cursor, row, "child_go_id"),
                parent_go_id=_required(cursor, row, "parent_go_id"),
                relation=_choice(cursor, row, "relation", GoRelation),
            )

    def _go_annotations(self, humans: Mapping[str, Protein]) -> Iterator[GoAnnotation]:
        for cursor, row in _rows(self.enrichment / GO_ANNOTATIONS):
            yield _make(
                cursor,
                GoAnnotation,
                protein=_resolve_human(cursor, humans, row),
                go_id=_required(cursor, row, "go_id"),
                evidence_code=_required(cursor, row, "evidence_code"),
                assigned_by=_text(cursor, row, "assigned_by"),
                qualifier=_text(cursor, row, "qualifier"),
            )
