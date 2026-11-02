"""Which release of each public dataset a run was built from.

Every fetcher records what it fetched in the run directory's `sources.tsv`:
the dataset, the URL, the day it was fetched and the release the source itself
names, where it names one. A run that is rebuilt a year later then says which
GO, which UniProt and which taxonomy its graph describes.
"""

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

COLUMNS = ("dataset", "url", "fetched", "release")


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


def record_source(path: Path, dataset: str, url: str, release: str) -> None:
    """Record one fetch, replacing whatever was recorded for that dataset."""
    kept = [source for source in read_sources(path) if source.dataset != dataset]
    kept.append(Source(dataset, url, date.today().isoformat(), release))
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for source in sorted(kept, key=lambda source: source.dataset):
            fields = (source.dataset, source.url, source.fetched, source.release)
            handle.write("\t".join(fields) + "\n")
