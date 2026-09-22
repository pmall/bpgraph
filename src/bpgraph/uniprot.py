"""UniProt `CC FUNCTION` text, fetched for the proteins an export names.

The relational database does not hold it, so it is fetched here and written
beside the taxonomy — `data/functions-2026-09-09.tsv` for the export directory
`data/graph-2026-09-09`, outside it because the file is this repo's and not
the relational database's, named after it because it is only true of that one
export. The loader reads it back from there; this module never touches the
graph, and that file is the only thing between the two. It is also the cache:
a fetch runs once per export, and every build after it reads what is there.

An entry is one accession, but a protein may be one chain of it: a viral
polyprotein carries a mature protein per chain, and UniProt scopes a FUNCTION
comment to a chain by naming its molecule. Matching the two goes by coordinates
rather than by name, because curation and UniProt disagree about the exact
boundary often enough — an export's NS5A ending at 2419 where UniProt's chain
ends at 2420 — while two chains of one entry never sit close enough for the
overlap to be ambiguous.

**Text that is not about the protein is not written.** An entry's own FUNCTION
describes the whole accession, which is the protein itself only where the
export names no other part of that accession. A polyprotein cut into four
mature proteins by an entry UniProt never split into chains has nothing to say
about any one of them, and all four keep an empty `function` rather than
sharing one text between them.
"""

import json
import logging
import time
import urllib.parse
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bpgraph.loaders.tsv import DATA_DIRECTORY, functions_path
from bpgraph.models import Protein

logger = logging.getLogger(__name__)

ACCESSIONS_URL = "https://rest.uniprot.org/uniprotkb/accessions"
FIELDS = ("accession", "cc_function", "ft_chain")
BATCH_SIZE = 100
"""The most accessions the endpoint takes in one request."""

FUNCTION = "FUNCTION"
CHAIN = "Chain"
COLUMNS = ("type", "accession", "start", "stop", "function")

MIN_OVERLAP = 0.8
"""How much a span and a chain must agree before the chain's text is the
protein's. Curation rounds a boundary by a residue or two; the next chain along
is hundreds away, so anything in between means the protein is not that chain."""

TIMEOUT = 60.0
ATTEMPTS = 4
BACKOFF = 3.0
RETRIABLE = frozenset({429, 500, 502, 503, 504})
"""Rate limiting and the gateway's bad days. Everything else is our bug."""


class _Position(TypedDict):
    value: int | None


class _Location(TypedDict):
    start: _Position
    end: _Position


class _Feature(TypedDict):
    type: str
    location: _Location
    description: NotRequired[str]


class _Text(TypedDict):
    value: str


class _Comment(TypedDict):
    commentType: str
    molecule: NotRequired[str]
    texts: NotRequired[list[_Text]]


class _Record(TypedDict):
    primaryAccession: str
    comments: NotRequired[list[_Comment]]
    features: NotRequired[list[_Feature]]


class _Response(TypedDict):
    results: list[_Record]


@dataclass(frozen=True, slots=True)
class Chain:
    """A FUNCTION comment UniProt scopes to one mature chain of an entry."""

    name: str
    start: int
    stop: int
    function: str

    def agreement(self, start: int, stop: int) -> float:
        """How much a span and this chain agree: shared residues over the
        residues either covers.

        Shared residues alone would tie the polyprotein's own chain with every
        chain inside it, since it covers all of them; dividing by the union is
        what prefers the tightest fit.
        """
        shared = min(stop, self.stop) - max(start, self.start) + 1
        if shared <= 0:
            return 0.0
        return shared / ((stop - start + 1) + (self.stop - self.start + 1) - shared)


@dataclass(frozen=True, slots=True)
class Entry:
    """One UniProt entry, reduced to the function text it carries.

    `function` is what the entry says about itself, and `chains` what it says
    about one mature chain at a time. A comment scoped to a molecule UniProt
    does not locate — an isoform, usually — is entry-level text under its own
    name: it describes the whole accession, and nothing else would ever reach
    it.
    """

    accession: str
    function: str
    chains: tuple[Chain, ...]

    def function_for(self, start: int, stop: int, whole_entry: bool) -> str:
        """What this entry says about one span of itself, and nothing wider.

        A span that is one of the chains takes that chain's text. A span that
        is not takes the entry's own — but only when `whole_entry` says the
        export names no other part of this accession, because the entry
        describes the accession and that is the protein only then. Failing
        both, it takes every chain it runs through, each under its name: a
        polyprotein describes its chains and never itself, and a protein
        covering several of them is covering exactly what they describe.

        Everything that survives is text about this protein. What is left is
        the empty string, which is what the schema means by unknown.
        """
        closest = max(
            self.chains, key=lambda chain: chain.agreement(start, stop), default=None
        )
        if closest is not None and closest.agreement(start, stop) >= MIN_OVERLAP:
            return closest.function
        if self.function and whole_entry:
            return self.function
        return " ".join(
            f"[{chain.name}]: {chain.function}"
            for chain in self.chains
            if chain.agreement(start, stop) > 0
        )


def _clean(text: str) -> str:
    """One line of text: the export holds no tab and no newline of its own."""
    return " ".join(text.split())


def _spans(record: _Record, molecule: str) -> list[tuple[int, int]]:
    """Where a named chain sits. A boundary UniProt does not know is no span."""
    located: list[tuple[int, int]] = []
    for feature in record.get("features", []):
        if feature["type"] != CHAIN or feature.get("description", "") != molecule:
            continue
        start = feature["location"]["start"]["value"]
        stop = feature["location"]["end"]["value"]
        if start is not None and stop is not None:
            located.append((start, stop))
    return located


def _entry(record: _Record) -> Entry:
    """One entry out of one response record."""
    entry_level: list[str] = []
    chains: list[Chain] = []
    for comment in record.get("comments", []):
        if comment["commentType"] != FUNCTION:
            continue
        text = _clean(" ".join(t["value"] for t in comment.get("texts", [])))
        if not text:
            continue
        molecule = comment.get("molecule", "")
        spans = _spans(record, molecule) if molecule else []
        if not spans:
            entry_level.append(f"[{molecule}]: {text}" if molecule else text)
        chains.extend(
            Chain(name=molecule, start=start, stop=stop, function=text)
            for start, stop in spans
        )
    return Entry(
        accession=record["primaryAccession"],
        function=" ".join(entry_level),
        chains=tuple(chains),
    )


def _request(accessions: Sequence[str]) -> _Response:
    """One batch, retried while the failure is UniProt's rather than ours."""
    url = f"{ACCESSIONS_URL}?" + urllib.parse.urlencode(
        {
            "accessions": ",".join(accessions),
            "fields": ",".join(FIELDS),
            "format": "json",
        }
    )
    attempt = 1
    while True:
        try:
            with urlopen(url, timeout=TIMEOUT) as response:
                return cast(_Response, json.load(response))
        except (URLError, TimeoutError) as error:
            if isinstance(error, HTTPError) and error.code not in RETRIABLE:
                raise
            if attempt == ATTEMPTS:
                raise
            delay = BACKOFF * attempt
            logger.warning("uniprot: %s, retrying in %.0fs", error, delay)
            time.sleep(delay)
            attempt += 1


def fetch(accessions: Iterable[str]) -> dict[str, Entry]:
    """Every entry UniProt still holds, keyed by accession.

    An accession it has retired comes back with nothing at all — deleted, or
    merged into another accession, and either way there is no text here to
    attach to it. Those proteins keep an empty `function`, exactly like the
    ones UniProt describes but says nothing about.
    """
    wanted = sorted(set(accessions))
    entries: dict[str, Entry] = {}
    for start in range(0, len(wanted), BATCH_SIZE):
        batch = wanted[start : start + BATCH_SIZE]
        for record in _request(batch)["results"]:
            entry = _entry(record)
            entries[entry.accession] = entry
        logger.info("uniprot: %d/%d accessions", start + len(batch), len(wanted))
    return entries


def _rows(proteins: Sequence[Protein]) -> Iterator[tuple[str, ...]]:
    """The file's rows: one per protein UniProt has something to say about.

    A human accession is always one protein, so the count below only ever
    narrows what a viral polyprotein is allowed to claim.
    """
    entries = fetch(protein.accession for protein in proteins)
    parts = Counter(protein.accession for protein in proteins)
    for protein in proteins:
        entry = entries.get(protein.accession)
        function = (
            entry.function_for(
                protein.start, protein.stop, parts[protein.accession] == 1
            )
            if entry
            else ""
        )
        if function:
            yield (
                protein.kind.value,
                protein.accession,
                str(protein.start),
                str(protein.stop),
                function,
            )


def write_functions(proteins: Iterable[Protein], path: Path) -> int:
    """Fetch the text for these proteins and write it. Returns the rows written.

    A protein UniProt says nothing about — or nothing attributable to it — gets
    no row: the loader builds it with `function` empty, which is what the
    schema means by unknown free text.

    Every entry is in hand before the file is opened, so a fetch that gives out
    part way leaves whatever was there already rather than half of it.
    """
    rows = tuple(_rows(tuple(proteins)))
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
    return len(rows)


def main() -> None:
    """Fetch the function text for one export directory's proteins.

    `uv run bpgraph-functions data/graph-2026-09-09` reads that export to learn
    which proteins it names, fetches their function text and writes
    `data/functions-2026-09-09.tsv`. Rebuilding is what puts the text in the
    graph.
    """
    import sys

    from bpgraph.loaders import TsvExport

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIRECTORY
    path = functions_path(directory)
    export = TsvExport(directory).load()
    written = write_functions(export.proteins, path)
    print(f"{path}: {written} of {len(export.proteins)} proteins have function text")
