"""Every reviewed UniProt entry of a host: the reference for a host protein.

A host protein's name, description and function text come from here, and so
does the set of accessions a host protein may have: every entry is a protein
of the graph, IntAct and GO are cut to them, and a curated host partner outside
them is dropped. One snapshot of about twenty thousand entries for human,
written into the host's silo as `swissprot.tsv`, with the sequences beside it
in `sequences.tsv` for the vault.

`name` is the primary gene symbol. An entry with none — a handful of
uncharacterized ORFs — is named after its accession, since the graph has no
empty name. `function` is the entry's `CC FUNCTION` text, joined the way
`bpgraph.uniprot` joins it, evidence stripped; `pmids` are the PubMed ids that
text cites as its evidence.
"""

import csv
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.parse import urlencode
from urllib.request import urlopen

from bpgraph.run import HUMAN, HostPaths, Run
from bpgraph.sources import record_source
from bpgraph.uniprot import FUNCTION, PMID_SEPARATOR, Text, cited, clean

logger = logging.getLogger(__name__)

STREAM_URL = "https://rest.uniprot.org/uniprotkb/stream"
FIELDS = ("accession", "gene_primary", "protein_name", "cc_function", "sequence")
COLUMNS = ("accession", "name", "description", "function", "pmids")
SEQUENCE_COLUMNS = ("accession", "sequence")


class _Value(TypedDict):
    value: str


class _Name(TypedDict):
    fullName: _Value


class _Description(TypedDict):
    recommendedName: NotRequired[_Name]
    submissionNames: NotRequired[list[_Name]]


class _Gene(TypedDict):
    geneName: NotRequired[_Value]


class _Comment(TypedDict):
    commentType: str
    molecule: NotRequired[str]
    texts: NotRequired[list[Text]]


class _Record(TypedDict):
    primaryAccession: str
    proteinDescription: _Description
    genes: NotRequired[list[_Gene]]
    comments: NotRequired[list[_Comment]]
    sequence: _Value


class _Response(TypedDict):
    results: list[_Record]


@dataclass(frozen=True, slots=True)
class Entry:
    accession: str
    name: str
    description: str
    function: str
    pmids: tuple[str, ...]


def _entry(record: _Record) -> Entry:
    accession = record["primaryAccession"]
    genes = [
        gene["geneName"]["value"]
        for gene in record.get("genes", [])
        if "geneName" in gene
    ]
    described = record["proteinDescription"]
    names = [described["recommendedName"]] if "recommendedName" in described else []
    names += described.get("submissionNames", [])
    functions: list[str] = []
    pmids: list[str] = []
    for comment in record.get("comments", []):
        if comment["commentType"] != FUNCTION:
            continue
        texts = comment.get("texts", [])
        text = clean(" ".join(t["value"] for t in texts))
        molecule = comment.get("molecule", "")
        if text:
            functions.append(f"[{molecule}]: {text}" if molecule else text)
            pmids.extend(cited(texts))
    return Entry(
        accession=accession,
        name=clean(genes[0]) if genes else accession,
        description=clean(names[0]["fullName"]["value"]) if names else "",
        function=" ".join(functions),
        pmids=tuple(dict.fromkeys(pmids)),
    )


def fetch(taxon_id: int) -> tuple[list[tuple[Entry, str]], str]:
    """Every reviewed entry of a host with its sequence, and the UniProt
    release they are from."""
    url = f"{STREAM_URL}?" + urlencode(
        {
            "query": f"reviewed:true AND organism_id:{taxon_id}",
            "fields": ",".join(FIELDS),
            "format": "json",
        }
    )
    logger.info("swiss-prot: fetching %s", url)
    with urlopen(url) as response:
        records = cast(_Response, json.load(response))["results"]
        release = response.headers.get("X-UniProt-Release", "")
    entries = [(_entry(record), record["sequence"]["value"]) for record in records]
    return sorted(entries, key=lambda pair: pair[0].accession), release


def write_swissprot(host: HostPaths, sources: Path) -> int:
    """Fetch and write `swissprot.tsv` and `sequences.tsv`. Returns the entries
    written."""
    entries, release = fetch(host.taxon_id)
    host.directory.mkdir(parents=True, exist_ok=True)
    with (
        host.swissprot.open("w", encoding="utf-8", newline="\n") as handle,
        host.sequences.open("w", encoding="utf-8", newline="\n") as sequences,
    ):
        handle.write("\t".join(COLUMNS) + "\n")
        sequences.write("\t".join(SEQUENCE_COLUMNS) + "\n")
        for entry, sequence in entries:
            fields = (
                entry.accession,
                entry.name,
                entry.description,
                entry.function,
                PMID_SEPARATOR.join(entry.pmids),
            )
            handle.write("\t".join(fields) + "\n")
            sequences.write(f"{entry.accession}\t{sequence}\n")
    record_source(sources, f"{host.taxon_id} swiss-prot", STREAM_URL, release)
    return len(entries)


def read_swissprot(path: Path) -> dict[str, Entry]:
    """The file, keyed by accession."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return {
            row["accession"]: Entry(
                accession=row["accession"],
                name=row["name"],
                description=row["description"],
                function=row["function"],
                pmids=tuple(p for p in row["pmids"].split(PMID_SEPARATOR) if p),
            )
            for row in reader
        }


def canonical(identifier: str) -> str:
    """The entry an isoform (`P04637-2`) or a chain (`P04637-PRO_0000185703`)
    belongs to."""
    return identifier.partition("-")[0]


def iter_accessions(path: Path) -> Iterator[str]:
    """The accessions of the file, without loading the text."""
    with path.open(encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            yield line.partition("\t")[0]


def main() -> None:
    """Fetch Swiss-Prot human into one run directory.

    `uv run bpgraph-swissprot data/2026-09-09` writes `hosts/9606/swissprot.tsv`
    and `sequences.tsv`, and records the fetch.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-swissprot <run directory>")
    run = Run(Path(sys.argv[1]))
    host = run.host(HUMAN)
    print(f"{host.swissprot}: {write_swissprot(host, run.sources)} entries")
