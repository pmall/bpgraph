"""A host's interactions: our curated rows, and IntAct's for the publications
we have not curated.

A description is one pair, one publication and one method. Each of our
curated rows is a description, keyed by its `stable_id`. An IntAct record is
skipped when one of our HH rows cites its publication: we read that
publication and decided what it shows, so all IntAct could add is what we
decided against. A publication we curated for VH rows only does not count:
IntAct's records here are human–human. The others add descriptions, the
records sharing a pair and a method being one.

Both sources are written to one file sorted on disk by publication, ours
first, so whether we curated a publication is known before its IntAct
records are read, and nothing else is held.

Everything else a host contributes — its proteins, their function text, its
GO — is read straight from its silo's files when the graph is written.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TextIO

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.loaders.records import KEPT, Curated, Description, of, pair_ref
from bpgraph.loaders.tsv import required, rows
from bpgraph.run import HostPaths

logger = logging.getLogger(__name__)

CURATED, INTACT = "0", "1"
"""Which source a row of the merge file comes from; ours sort first."""


def _merge_keys(host: HostPaths, curated: Path) -> Iterator[list[str]]:
    """`[pmid, source, a, b, psimi_id, stable_id]`, the pair in sorted order."""
    for cursor, row in rows(host.intact):
        a, b = sorted(
            (required(cursor, row, "accession1"), required(cursor, row, "accession2"))
        )
        yield [
            required(cursor, row, "pmid"),
            INTACT,
            a,
            b,
            required(cursor, row, "psimi_id"),
            "",
        ]
    for record in files.read(curated):
        row = of(Curated, record)
        if row.kind != InteractionKind.HH.value or row.status != KEPT:
            continue
        a, b = sorted((row.accession_1, row.accession_2))
        yield [row.pmid, CURATED, a, b, row.psimi_id, row.stable_id]


def hh_descriptions(
    host: HostPaths,
    curated: Path,
    scratch: Path,
    name_of: Callable[[str], str],
    out: TextIO,
) -> None:
    """Write the host's descriptions."""
    merged = files.sorted_file(scratch / "hh_merge", _merge_keys(host, curated))
    counts = {"curated": 0, "intact": 0, "intact_dropped": 0}

    def write(a: str, b: str, pmid: str, psimi_id: str, stable_id: str) -> None:
        row = Description(
            interaction=pair_ref(a, b),
            kind=InteractionKind.HH.value,
            side_a=a,
            side_b=b,
            pmid=pmid,
            method_id=psimi_id,
            method_name=name_of(psimi_id),
            stable_id=stable_id,
        )
        out.write("\t".join(row) + "\n")

    for (pmid,), found in files.groups(files.read(merged), 1):
        ours = [r for r in found if r[1] == CURATED]
        if ours:
            counts["intact_dropped"] += len(found) - len(ours)
            for _, _, a, b, psimi_id, stable_id in ours:
                write(a, b, pmid, psimi_id, stable_id)
            counts["curated"] += len(ours)
            continue
        observed = sorted({(r[2], r[3], r[4]) for r in found})
        for a, b, psimi_id in observed:
            write(a, b, pmid, psimi_id, "")
        counts["intact"] += len(observed)
    logger.info(
        "%d HH: %d curated descriptions; %d IntAct descriptions of publications "
        "we have not curated; %d IntAct records of publications we curated dropped",
        host.taxon_id,
        counts["curated"],
        counts["intact"],
        counts["intact_dropped"],
    )
