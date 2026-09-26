"""UniProt `CC FUNCTION` text and sequences, fetched for the viral silo.

The relational database holds neither, so they are fetched here and written
into the viral silo — `data/2026-09-09/viral/functions.tsv` and `entries.tsv`.
The loader reads them back from there; this module never touches the graph.
It is also the cache: a fetch runs once per export, and every build after it
reads what is there. Host proteins get theirs from `bpgraph.swissprot`.

An entry is one accession, but a viral protein is one chain of it: a
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

A text's `pmids` are the PubMed ids UniProt cites as its evidence.
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

from bpgraph.run import ViralPaths
from bpgraph.sources import record_source

logger = logging.getLogger(__name__)

ACCESSIONS_URL = "https://rest.uniprot.org/uniprotkb/accessions"
FIELDS = ("accession", "cc_function", "ft_chain", "sequence")
BATCH_SIZE = 100
"""The most accessions the endpoint takes in one request."""

FUNCTION = "FUNCTION"
CHAIN = "Chain"
PUBMED = "PubMed"
PMID_SEPARATOR = ";"
COLUMNS = ("accession", "start", "stop", "function", "pmids")
ENTRY_COLUMNS = ("accession", "sequence")

MIN_OVERLAP = 0.8
"""How much a span and a chain must agree before the chain's text is the
protein's. Curation rounds a boundary by a residue or two; the next chain along
is hundreds away, so anything in between means the protein is not that chain."""

TIMEOUT = 60.0
ATTEMPTS = 4
BACKOFF = 3.0
RETRIABLE = frozenset({429, 500, 502, 503, 504})
"""Rate limiting and the gateway's bad days. Everything else is our bug."""

type Site = tuple[str, int, int]
"""Where a viral protein was observed: accession, start, stop."""


class _Evidence(TypedDict):
    source: NotRequired[str]
    id: NotRequired[str]


class Text(TypedDict):
    value: str
    evidences: NotRequired[list[_Evidence]]


class _Position(TypedDict):
    value: int | None


class _Location(TypedDict):
    start: _Position
    end: _Position


class _Feature(TypedDict):
    type: str
    location: _Location
    description: NotRequired[str]


class _Comment(TypedDict):
    commentType: str
    molecule: NotRequired[str]
    texts: NotRequired[list[Text]]


class _Sequence(TypedDict):
    value: str


class _Record(TypedDict):
    primaryAccession: str
    comments: NotRequired[list[_Comment]]
    features: NotRequired[list[_Feature]]
    sequence: _Sequence


class _Response(TypedDict):
    results: list[_Record]


@dataclass(frozen=True, slots=True)
class _Batch:
    records: list[_Record]
    release: str
    """UniProt's release, from the response's `X-UniProt-Release` header."""


def clean(text: str) -> str:
    """One line of text: a TSV cell holds no tab and no newline."""
    return " ".join(text.split())


def cited(texts: Iterable[Text]) -> list[str]:
    """The PubMed ids a comment's texts cite, in order, once each."""
    pmids = (
        evidence.get("id", "")
        for text in texts
        for evidence in text.get("evidences", [])
        if evidence.get("source") == PUBMED
    )
    return list(dict.fromkeys(p for p in pmids if p.isdigit()))


@dataclass(frozen=True, slots=True)
class Function:
    """A text, and the publications UniProt cites for it."""

    text: str
    pmids: tuple[str, ...]


NO_FUNCTION = Function("", ())


@dataclass(frozen=True, slots=True)
class Chain:
    """A FUNCTION comment UniProt scopes to one mature chain of an entry."""

    name: str
    start: int
    stop: int
    function: Function

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
    """One UniProt entry, reduced to its sequence and the function text it
    carries.

    `function` is what the entry says about itself, and `chains` what it says
    about one mature chain at a time. A comment scoped to a molecule UniProt
    does not locate — an isoform, usually — is entry-level text under its own
    name: it describes the whole accession, and nothing else would ever reach
    it.
    """

    accession: str
    sequence: str
    function: Function
    chains: tuple[Chain, ...]

    def function_for(self, start: int, stop: int, whole_entry: bool) -> Function:
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
        if self.function.text and whole_entry:
            return self.function
        covered = [c for c in self.chains if c.agreement(start, stop) > 0]
        return Function(
            text=" ".join(f"[{c.name}]: {c.function.text}" for c in covered),
            pmids=tuple(dict.fromkeys(p for c in covered for p in c.function.pmids)),
        )


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
    entry_pmids: list[str] = []
    chains: list[Chain] = []
    for comment in record.get("comments", []):
        if comment["commentType"] != FUNCTION:
            continue
        texts = comment.get("texts", [])
        text = clean(" ".join(t["value"] for t in texts))
        if not text:
            continue
        pmids = cited(texts)
        molecule = comment.get("molecule", "")
        spans = _spans(record, molecule) if molecule else []
        if not spans:
            entry_level.append(f"[{molecule}]: {text}" if molecule else text)
            entry_pmids.extend(pmids)
        chains.extend(
            Chain(
                name=molecule,
                start=start,
                stop=stop,
                function=Function(text, tuple(pmids)),
            )
            for start, stop in spans
        )
    return Entry(
        accession=record["primaryAccession"],
        sequence=record["sequence"]["value"],
        function=Function(" ".join(entry_level), tuple(dict.fromkeys(entry_pmids))),
        chains=tuple(chains),
    )


def _request(accessions: Sequence[str]) -> _Batch:
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
                return _Batch(
                    records=cast(_Response, json.load(response))["results"],
                    release=response.headers.get("X-UniProt-Release", ""),
                )
        except (URLError, TimeoutError) as error:
            if isinstance(error, HTTPError) and error.code not in RETRIABLE:
                raise
            if attempt == ATTEMPTS:
                raise
            delay = BACKOFF * attempt
            logger.warning("uniprot: %s, retrying in %.0fs", error, delay)
            time.sleep(delay)
            attempt += 1


def fetch(accessions: Iterable[str]) -> tuple[dict[str, Entry], str]:
    """Every entry UniProt still holds, keyed by accession.

    An accession it has retired comes back with nothing at all — deleted, or
    merged into another accession, and either way there is no text here to
    attach to it and no sequence for the vault. Returns the release too.
    """
    wanted = sorted(set(accessions))
    entries: dict[str, Entry] = {}
    releases: set[str] = set()
    for start in range(0, len(wanted), BATCH_SIZE):
        batch = wanted[start : start + BATCH_SIZE]
        response = _request(batch)
        releases.add(response.release)
        for record in response.records:
            entry = _entry(record)
            entries[entry.accession] = entry
        logger.info("uniprot: %d/%d accessions", start + len(batch), len(wanted))
    if len(releases) > 1:
        logger.warning("uniprot: the release changed mid-fetch: %s", sorted(releases))
    return entries, ",".join(sorted(releases))


def _rows(
    sites: Sequence[Site], entries: dict[str, Entry]
) -> Iterator[tuple[str, ...]]:
    """The file's rows: one per entry and span UniProt has something to say
    about. An accession named at one span only is the protein as a whole."""
    parts = Counter(accession for accession, _, _ in sites)
    for accession, start, stop in sites:
        entry = entries.get(accession)
        function = (
            entry.function_for(start, stop, parts[accession] == 1)
            if entry
            else NO_FUNCTION
        )
        if function.text:
            yield (
                accession,
                str(start),
                str(stop),
                function.text,
                PMID_SEPARATOR.join(function.pmids),
            )


def write_viral(sites: Iterable[Site], viral: ViralPaths) -> tuple[int, int, str]:
    """Fetch the text for every viral entry and span, and every viral entry's
    sequence, and write both. Returns the function rows and entries written,
    and the UniProt release they came from.

    Every entry is in hand before a file is opened, so a fetch that gives out
    part way leaves whatever was there already rather than half of it.
    """
    wanted = tuple(sorted(set(sites)))
    entries, release = fetch(accession for accession, _, _ in wanted)
    rows = tuple(_rows(wanted, entries))
    viral.directory.mkdir(parents=True, exist_ok=True)
    with viral.functions.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")
    with viral.entries.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(ENTRY_COLUMNS) + "\n")
        for accession in sorted(entries):
            handle.write(f"{accession}\t{entries[accession].sequence}\n")
    return len(rows), len(entries), release


def main() -> None:
    """Fetch the viral silo's function text and sequences.

    `uv run bpgraph-functions data/2026-09-09` reads that run's export to learn
    which viral entries and spans it names, and writes `viral/functions.tsv`
    and `viral/entries.tsv`. Rebuilding is what puts them in the graph and the
    vault.
    """
    import sys

    from bpgraph.loaders.export import viral_sites
    from bpgraph.run import Run

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-functions <run directory>")
    run = Run(Path(sys.argv[1]))
    sites = viral_sites(run.export)
    written, entries, release = write_viral(sites, run.viral)
    record_source(run.sources, "viral uniprot", ACCESSIONS_URL, release)
    accessions = len({accession for accession, _, _ in sites})
    print(
        f"{run.viral.functions}: {written} of {len(sites)} spans have function text\n"
        f"{run.viral.entries}: {entries} of {accessions} entries have a sequence"
    )
