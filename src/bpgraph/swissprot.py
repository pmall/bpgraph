"""Every reviewed human UniProt entry: the reference for a human protein.

A human protein's name, description and function text come from here, not
from the export, and so does the set of accessions a human partner may have:
IntAct is filtered to it, and consolidation fails on a human accession it does
not hold. One snapshot of about twenty thousand entries, written into the run
directory as `swissprot_human.tsv`.

`name` is the primary gene symbol. An entry with none — a handful of
uncharacterized ORFs — is named after its accession, since the graph has no
empty name. `function` is the entry's `CC FUNCTION` text, joined the way
`bpgraph.uniprot` joins it, evidence stripped.
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

from bpgraph.run import Run
from bpgraph.sources import record_source
from bpgraph.uniprot import FUNCTION

logger = logging.getLogger(__name__)

STREAM_URL = "https://rest.uniprot.org/uniprotkb/stream"
QUERY = "reviewed:true AND organism_id:9606"
FIELDS = ("accession", "gene_primary", "protein_name", "cc_function")
COLUMNS = ("accession", "name", "description", "function")


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
    texts: NotRequired[list[_Value]]


class _Record(TypedDict):
    primaryAccession: str
    proteinDescription: _Description
    genes: NotRequired[list[_Gene]]
    comments: NotRequired[list[_Comment]]


class _Response(TypedDict):
    results: list[_Record]


@dataclass(frozen=True, slots=True)
class Entry:
    accession: str
    name: str
    description: str
    function: str


def _clean(text: str) -> str:
    """One line of text: a TSV cell holds no tab and no newline."""
    return " ".join(text.split())


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
    for comment in record.get("comments", []):
        if comment["commentType"] != FUNCTION:
            continue
        text = _clean(" ".join(t["value"] for t in comment.get("texts", [])))
        molecule = comment.get("molecule", "")
        if text:
            functions.append(f"[{molecule}]: {text}" if molecule else text)
    return Entry(
        accession=accession,
        name=_clean(genes[0]) if genes else accession,
        description=_clean(names[0]["fullName"]["value"]) if names else "",
        function=" ".join(functions),
    )


def fetch() -> tuple[list[Entry], str]:
    """Every reviewed human entry, and the UniProt release they are from."""
    url = f"{STREAM_URL}?" + urlencode(
        {"query": QUERY, "fields": ",".join(FIELDS), "format": "json"}
    )
    logger.info("swiss-prot: fetching %s", url)
    with urlopen(url) as response:
        records = cast(_Response, json.load(response))["results"]
        release = response.headers.get("X-UniProt-Release", "")
    return sorted(
        (_entry(record) for record in records), key=lambda e: e.accession
    ), release


def write_swissprot(run: Run) -> int:
    """Fetch and write `swissprot_human.tsv`. Returns the entries written."""
    entries, release = fetch()
    with run.swissprot.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for entry in entries:
            handle.write(
                "\t".join(
                    (entry.accession, entry.name, entry.description, entry.function)
                )
                + "\n"
            )
    record_source(run.sources, "swiss-prot", STREAM_URL, release)
    return len(entries)


def read_swissprot(path: Path) -> dict[str, Entry]:
    """The file, keyed by accession."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return {row["accession"]: Entry(**row) for row in reader}


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

    `uv run bpgraph-swissprot data/2026-09-09` writes `swissprot_human.tsv`
    beside the export and records the fetch.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-swissprot <run directory>")
    run = Run(Path(sys.argv[1]))
    print(f"{run.swissprot}: {write_swissprot(run)} entries")
