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

import json
import logging
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict, cast
from urllib.parse import urlencode
from urllib.request import urlopen

from bpgraph import files
from bpgraph.run import HUMAN, HostPaths, Run
from bpgraph.sources import record_source
from bpgraph.uniprot import (
    FUNCTION,
    PMID_SEPARATOR,
    ProteinDescription,
    Text,
    cited,
    clean,
    function_text,
    protein_name,
)

logger = logging.getLogger(__name__)

SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
PAGE_SIZE = 500
NEXT = re.compile(r'<([^>]+)>; rel="next"')
FIELDS = ("accession", "gene_primary", "protein_name", "cc_function", "sequence")
COLUMNS = ("accession", "name", "description", "function", "pmids")
SEQUENCE_COLUMNS = ("accession", "sequence")


class _Value(TypedDict):
    value: str


class _Gene(TypedDict):
    geneName: NotRequired[_Value]


class _Comment(TypedDict):
    commentType: str
    molecule: NotRequired[str]
    texts: NotRequired[list[Text]]


class _Record(TypedDict):
    primaryAccession: str
    proteinDescription: ProteinDescription
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
    functions: list[str] = []
    pmids: list[str] = []
    for comment in record.get("comments", []):
        if comment["commentType"] != FUNCTION:
            continue
        texts = comment.get("texts", [])
        text = function_text(" ".join(t["value"] for t in texts))
        molecule = comment.get("molecule", "")
        if text:
            functions.append(f"[{molecule}]: {text}" if molecule else text)
            pmids.extend(cited(texts))
    return Entry(
        accession=accession,
        name=clean(genes[0]) if genes else accession,
        description=protein_name(record["proteinDescription"]),
        function=" ".join(functions),
        pmids=tuple(dict.fromkeys(pmids)),
    )


def _pages(taxon_id: int) -> Iterator[tuple[list[_Record], str]]:
    """Every reviewed entry of a host, a page at a time, with the release each
    page is from. UniProt links each page to the next one."""
    url: str | None = f"{SEARCH_URL}?" + urlencode(
        {
            "query": f"reviewed:true AND organism_id:{taxon_id}",
            "fields": ",".join(FIELDS),
            "format": "json",
            "size": PAGE_SIZE,
        }
    )
    while url is not None:
        with urlopen(url) as response:
            records = cast(_Response, json.load(response))["results"]
            release = response.headers.get("X-UniProt-Release", "")
            following = NEXT.search(response.headers.get("Link", ""))
        yield records, release
        url = following.group(1) if following else None


def write_swissprot(host: HostPaths, sources: Path) -> int:
    """Fetch and write `swissprot.tsv` and `sequences.tsv`, each sorted by
    accession. Returns the entries written."""
    host.directory.mkdir(parents=True, exist_ok=True)
    releases: set[str] = set()
    with tempfile.TemporaryDirectory(dir=host.directory) as directory:
        entries, sequences = Path(directory) / "entries", Path(directory) / "sequences"
        with (
            entries.open("w", encoding="utf-8", newline="\n") as e,
            sequences.open("w", encoding="utf-8", newline="\n") as q,
        ):
            fetched = 0
            for records, release in _pages(host.taxon_id):
                releases.add(release)
                fetched += len(records)
                for record in records:
                    entry = _entry(record)
                    fields = (
                        entry.accession,
                        entry.name,
                        entry.description,
                        entry.function,
                        PMID_SEPARATOR.join(entry.pmids),
                    )
                    e.write("\t".join(fields) + "\n")
                    q.write(f"{entry.accession}\t{record['sequence']['value']}\n")
                logger.info("swiss-prot: %d entries", fetched)
        written = files.write_table(
            host.swissprot, COLUMNS, files.read(files.sort(entries))
        )
        files.write_table(
            host.sequences, SEQUENCE_COLUMNS, files.read(files.sort(sequences))
        )
    if len(releases) > 1:
        logger.warning(
            "swiss-prot: the release changed mid-fetch: %s", sorted(releases)
        )
    record_source(
        sources, f"{host.taxon_id} swiss-prot", SEARCH_URL, ",".join(sorted(releases))
    )
    return written


def canonical(identifier: str) -> str:
    """The entry an isoform (`P04637-2`) or a chain (`P04637-PRO_0000185703`)
    belongs to."""
    return identifier.partition("-")[0]


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
