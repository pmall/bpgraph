"""The curated publication groups: publications that report one experiment
again, whose IntAct rows are resolved as a whole.

`curation/publications.tsv` has one row per publication: its `group`, its
`pmid` and a `note`. Within a group, a protein pair keeps the IntAct rows of
the lowest pmid that reports it, and drops the others. `curation/publications.md`
says why.
"""

import csv
from collections import Counter
from pathlib import Path

CURATED = Path(__file__).resolve().parents[2] / "curation" / "publications.tsv"


def read_groups(path: Path = CURATED) -> dict[str, str]:
    """The group of each grouped pmid. A pmid is in one group, and a group
    has at least two."""
    groups: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        for line, row in enumerate(reader, start=2):
            group, pmid = row["group"].strip(), row["pmid"].strip()
            if not group or not pmid.isdigit():
                raise ValueError(f"{path.name}:{line}: a group and a numeric pmid")
            if pmid in groups:
                raise ValueError(f"{path.name}:{line}: pmid {pmid} repeats")
            groups[pmid] = group
    alone = [g for g, n in Counter(groups.values()).items() if n < 2]
    if alone:
        raise ValueError(f"{path.name}: groups of one publication: {sorted(alone)}")
    return groups
