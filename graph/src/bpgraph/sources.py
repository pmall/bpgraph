"""Which release of each public dataset a run was built from.

Every fetcher records what it fetched in the run directory's `sources.tsv`:
the dataset, the URL, the day it was fetched and the release the source itself
names, where it names one, as each fetcher's docstring says. A run that is
rebuilt a year later then says which GO, which UniProt and which taxonomy its
graph describes, and `bpgraph-build` prints them.

The file has a header, `dataset`, `url`, `fetched` and `release`, then one row
per dataset, sorted, each fetch replacing its dataset's row. A dataset fetched
for one silo is named after it, `9606 intact` or `viral pubmed`; one every silo
shares is named alone, `psi-mi`.
"""

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

COLUMNS = ("dataset", "url", "fetched", "release")

DATED = re.compile(r"(\d{4}-\d{2}-\d{2})/")
"""A release directory of an archive, named after its date, `2026-01-09/`."""


@dataclass(frozen=True, slots=True)
class Source:
    dataset: str
    url: str
    fetched: str
    release: str


def read_sources(path: Path) -> list[Source]:
    """What the file records, or nothing if no fetcher has run yet."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [Source(**{column: row[column] for column in COLUMNS}) for row in reader]


def dated_release(index: str, cutoff: date) -> str:
    """The release current on `cutoff` of an archive whose index page lists
    one directory per release, named after its date: the latest on or before
    it."""
    request = Request(index, headers={"User-Agent": "bpgraph"})
    with urlopen(request) as response:
        page = response.read().decode("utf-8")
    released = {date.fromisoformat(d) for d in DATED.findall(page)}
    current = max((d for d in released if d <= cutoff), default=None)
    if current is None:
        raise ValueError(f"{index}: no release on or before {cutoff}")
    return current.isoformat()


def record_source(path: Path, dataset: str, url: str, release: str) -> None:
    """Record one fetch, replacing whatever was recorded for that dataset."""
    kept = [source for source in read_sources(path) if source.dataset != dataset]
    kept.append(Source(dataset, url, date.today().isoformat(), release))
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for source in sorted(kept, key=lambda source: source.dataset):
            fields = (source.dataset, source.url, source.fetched, source.release)
            handle.write("\t".join(fields) + "\n")
