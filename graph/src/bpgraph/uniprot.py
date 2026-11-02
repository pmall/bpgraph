"""UniProt `CC FUNCTION` text and protein names, fetched for the viral silo.

`bpgraph-functions RUN` reads the run's export to learn which viral entries
and spans it names, fetches them from UniProt and writes, sorted, the run's
`viral/functions.tsv`, one row per text of an entry and span: `accession`,
`start`, `stop`, `function` and `pmids`, `;`-separated; and `viral/entries.tsv`,
each entry's protein name: `accession` and `description`. It records the fetch
in `sources.tsv`, its release UniProt's `X-UniProt-Release`. Rebuilding is what
puts them in the graph.

The export holds neither, so they are fetched here. Sequences are not fetched:
the export carries each mature protein's own. The build reads these files;
this module never touches the graph. They are also the cache: a fetch runs once
per export, and every build after it reads what is there. Host proteins get
theirs from `bpgraph.swissprot`.

An entry is one accession, but a viral protein is one chain of it: a
polyprotein carries a mature protein per chain, and UniProt scopes a FUNCTION
comment to a chain by naming its molecule. Matching the two goes by coordinates
rather than by name, because curation and UniProt disagree about the exact
boundary often enough — an export's NS5A ending at 2419 where UniProt's chain
ends at 2420 — while two chains of one entry never sit close enough for the
overlap to be ambiguous.

**Only reviewed entries give function text**, for the reason
docs/schema.md#protein gives; an unreviewed entry's protein name is kept.

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
import re
import tempfile
import time
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from http.client import HTTPMessage, IncompleteRead
from itertools import batched
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bpgraph import files
from bpgraph.files import clean
from bpgraph.loaders.export import VIRAL_SITES, export_file
from bpgraph.loaders.tsv import rows
from bpgraph.run import ViralPaths, command_line
from bpgraph.sources import record_source

logger = logging.getLogger(__name__)

ACCESSIONS_URL = "https://rest.uniprot.org/uniprotkb/accessions"
FIELDS = ("accession", "protein_name", "cc_function", "ft_chain")
BATCH_SIZE = 100
"""The most accessions the endpoint takes in one request."""

FUNCTION = "FUNCTION"
REVIEWED = "UniProtKB reviewed (Swiss-Prot)"
CHAIN = "Chain"
PUBMED = "PubMed"
PMID_SEPARATOR = ";"
COLUMNS = ("accession", "start", "stop", "function", "pmids")
ENTRY_COLUMNS = ("accession", "description")

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


class Comment(TypedDict):
    commentType: str
    molecule: NotRequired[str]
    texts: NotRequired[list[Text]]


class Value(TypedDict):
    value: str


class _Name(TypedDict):
    fullName: Value


class ProteinDescription(TypedDict):
    recommendedName: NotRequired[_Name]
    submissionNames: NotRequired[list[_Name]]


class _Record(TypedDict):
    primaryAccession: str
    entryType: str
    proteinDescription: ProteinDescription
    comments: NotRequired[list[Comment]]
    features: NotRequired[list[_Feature]]


class _Response(TypedDict):
    results: list[_Record]


def get(url: str, label: str) -> tuple[object, HTTPMessage]:
    """A UniProt REST response, parsed from JSON, and its headers, retried
    while the failure is UniProt's rather than ours. `label` names the fetch
    in the warning a retry logs."""
    attempt = 1
    while True:
        try:
            with urlopen(url, timeout=TIMEOUT) as response:
                return json.load(response), response.headers
        except (URLError, TimeoutError, ConnectionError, IncompleteRead) as error:
            if isinstance(error, HTTPError) and error.code not in RETRIABLE:
                raise
            if attempt == ATTEMPTS:
                raise
            delay = BACKOFF * attempt
            logger.warning("%s: %s, retrying in %.0fs", label, error, delay)
            time.sleep(delay)
            attempt += 1


CITATIONS = re.compile(r"\s*\((?:PubMed|Ref\.)[^()]*\)")
"""The references UniProt sometimes leaves inline, `(PubMed:2359621,
PubMed:9054408)`. They are cited as evidence already."""


def function_text(value: str) -> str:
    """One text of a FUNCTION comment, on one line, its inline references
    removed."""
    return clean(CITATIONS.sub("", value))


def protein_name(described: ProteinDescription) -> str:
    """The entry's recommended name, or else the first submitted one."""
    names = [described["recommendedName"]] if "recommendedName" in described else []
    names += described.get("submissionNames", [])
    return clean(names[0]["fullName"]["value"]) if names else ""


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
    """One UniProt entry, reduced to its protein name and the function text
    it carries.

    `function` is what the entry says about itself, and `chains` what it says
    about one mature chain at a time. A comment scoped to a molecule UniProt
    does not locate — an isoform, usually — is entry-level text under its own
    name: it describes the whole accession, and nothing else would ever reach
    it.
    """

    accession: str
    description: str
    function: tuple[Function, ...]
    chains: tuple[Chain, ...]

    def function_for(
        self, start: int, stop: int, whole_entry: bool
    ) -> tuple[Function, ...]:
        """What this entry says about one span of itself, and nothing wider.

        A span that is one of the chains takes that chain's text. A span that
        is not takes the entry's own — but only when `whole_entry` says the
        export names no other part of this accession, because the entry
        describes the accession and that is the protein only then. Failing
        both, it takes every chain it runs through, each under its name: a
        polyprotein describes its chains and never itself, and a protein
        covering several of them is covering exactly what they describe.

        Everything that survives is text about this protein, one text at a
        time as UniProt gives them. What is left is nothing, which is what the
        schema means by unknown.
        """
        closest = max(
            self.chains, key=lambda chain: chain.agreement(start, stop), default=None
        )
        if closest is not None and closest.agreement(start, stop) >= MIN_OVERLAP:
            return (closest.function,)
        if self.function and whole_entry:
            return self.function
        return tuple(
            Function(f"[{c.name}]: {c.function.text}", c.function.pmids)
            for c in self.chains
            if c.agreement(start, stop) > 0
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
    """One entry out of one response record, each FUNCTION text a function of
    its own. An unreviewed entry's text is automatic annotation citing no
    publication, so only a reviewed entry has any."""
    entry_level: list[Function] = []
    chains: list[Chain] = []
    reviewed = record["entryType"] == REVIEWED
    for comment in record.get("comments", []) if reviewed else ():
        if comment["commentType"] != FUNCTION:
            continue
        molecule = comment.get("molecule", "")
        spans = _spans(record, molecule) if molecule else []
        for text in comment.get("texts", []):
            value = function_text(text["value"])
            if not value:
                continue
            function = Function(value, tuple(cited([text])))
            if not spans:
                entry_level.append(
                    Function(f"[{molecule}]: {value}", function.pmids)
                    if molecule
                    else function
                )
            chains.extend(
                Chain(name=molecule, start=start, stop=stop, function=function)
                for start, stop in spans
            )
    return Entry(
        accession=record["primaryAccession"],
        description=protein_name(record["proteinDescription"]),
        function=tuple(entry_level),
        chains=tuple(chains),
    )


def _request(accessions: Sequence[str]) -> tuple[list[_Record], str]:
    """One batch, and the UniProt release it is from."""
    url = f"{ACCESSIONS_URL}?" + urllib.parse.urlencode(
        {
            "accessions": ",".join(accessions),
            "fields": ",".join(FIELDS),
            "format": "json",
        }
    )
    body, headers = get(url, "uniprot")
    return cast(_Response, body)["results"], headers.get("X-UniProt-Release", "")


def write_viral(export: Path, viral: ViralPaths, sources: Path) -> tuple[int, int, int]:
    """Fetch the function text of every viral entry and span the export names,
    and every such entry's protein name, and write both, sorted. Returns the
    function rows written, the entries UniProt still holds and the entries
    asked for.

    The spans are read sorted by accession, a hundred accessions to a request;
    an accession named at one span only is the protein as a whole. An accession
    UniProt has retired comes back with nothing, and gets no row: curation
    keeps such an entry as it recorded it, but UniProt has nothing to say
    about it any more.
    """
    viral.directory.mkdir(parents=True, exist_ok=True)
    releases: set[str] = set()
    asked = held = 0
    with tempfile.TemporaryDirectory(dir=viral.directory) as directory:
        scratch = Path(directory)
        sites = files.sorted_file(
            scratch / "sites",
            (
                [row["accession"], row["start"], row["stop"]]
                for _, row in rows(export_file(export, VIRAL_SITES))
            ),
            unique=True,
        )
        texts, names = scratch / "functions", scratch / "entries"
        with (
            texts.open("w", encoding="utf-8", newline="\n") as t,
            names.open("w", encoding="utf-8", newline="\n") as n,
        ):
            for batch in batched(
                files.groups(files.read(sites), 1), BATCH_SIZE, strict=False
            ):
                records, release = _request([accession for (accession,), _ in batch])
                releases.add(release)
                entries = {e.accession: e for e in map(_entry, records)}
                asked += len(batch)
                held += len(entries)
                for (accession,), spans in batch:
                    entry = entries.get(accession)
                    if entry is None:
                        continue
                    n.write(f"{accession}\t{entry.description}\n")
                    for _, start, stop in spans:
                        for function in entry.function_for(
                            int(start), int(stop), len(spans) == 1
                        ):
                            pmids = PMID_SEPARATOR.join(function.pmids)
                            t.write(
                                f"{accession}\t{start}\t{stop}\t{function.text}\t{pmids}\n"
                            )
                logger.info("uniprot: %d accessions", asked)
        written = files.write_table(
            viral.functions, COLUMNS, files.read(files.sort(texts))
        )
        files.write_table(viral.entries, ENTRY_COLUMNS, files.read(files.sort(names)))
    if len(releases) > 1:
        logger.warning("uniprot: the release changed mid-fetch: %s", sorted(releases))
    record_source(sources, "viral uniprot", ACCESSIONS_URL, ",".join(sorted(releases)))
    return written, held, asked


def main() -> None:
    run = command_line(__doc__)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    written, held, asked = write_viral(run.export, run.viral, run.sources)
    print(
        f"{run.viral.functions}: {written} function texts\n"
        f"{run.viral.entries}: {held} of {asked} entries are in UniProt"
    )
