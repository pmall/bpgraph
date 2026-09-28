"""A host's interactions: IntAct's, with our curated rows merged onto them.

A curated row *is* an IntAct description when both have the same pair, the
same pmid and the same method class; it then adds its `stable_id` to that
description rather than being a description of its own. One IntAct pmid may
hold several descriptions of one pair in one class, and every curated row
matching them goes to the one with the lowest IntAct id, so a build is
deterministic. A curated row IntAct has not got is a description of its own.

Both sources are written to one file keyed by pair, pmid and class, IntAct
first and in IntAct order within a key, and sorted on disk: a key's rows then
arrive together, and nothing else is held.

Everything else a host contributes — its proteins, their function text, its
GO — is read straight from its silo's files when the graph is written.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TextIO

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.ids import intact_description_id, interaction_id
from bpgraph.loaders.records import KEPT, Curated, Description, of
from bpgraph.loaders.tsv import LoadError, required, rows
from bpgraph.run import HostPaths

logger = logging.getLogger(__name__)

INTACT, CURATED = "0", "1"
"""Which source a row of the merge file comes from; IntAct's sort first."""


def _order(intact_id: str) -> str:
    """IntAct ids by number, `EBI-99` before `EBI-100`, as text that sorts."""
    digits = intact_id.rpartition("-")[2]
    return f"{int(digits):015d}" if digits.isdigit() else "9" * 15


def _merge_keys(
    host: HostPaths,
    curated: Path,
    class_of: Callable[[str], str | None],
    uncurated: set[str],
) -> Iterator[list[str]]:
    """`[a, b, pmid, class, source, order, intact_id, psimi_id, stable_id]`."""
    for cursor, row in rows(host.intact):
        psimi_id = required(cursor, row, "psimi_id")
        method_class = class_of(psimi_id)
        if method_class is None:
            uncurated.add(psimi_id)
            continue
        intact_id = required(cursor, row, "intact_id")
        yield [
            required(cursor, row, "accession1"),
            required(cursor, row, "accession2"),
            required(cursor, row, "pmid"),
            method_class,
            INTACT,
            _order(intact_id),
            intact_id,
            psimi_id,
            "",
        ]
    for record in files.read(curated):
        row = of(Curated, record)
        if row.kind != InteractionKind.HH.value or row.status != KEPT:
            continue
        a, b = sorted((row.accession_1, row.accession_2))
        yield [
            a,
            b,
            row.pmid,
            row.method_class,
            CURATED,
            "",
            "",
            row.psimi_id,
            row.stable_id,
        ]


def hh_descriptions(
    host: HostPaths,
    curated: Path,
    scratch: Path,
    class_of: Callable[[str], str | None],
    name_of: Callable[[str], str],
    uncurated: set[str],
    out: TextIO,
) -> None:
    """Write the host's descriptions. Methods with no curated class are added
    to `uncurated`, for the caller to fail on."""
    merged = files.sorted_file(
        scratch / "hh_merge", _merge_keys(host, curated, class_of, uncurated)
    )
    counts = {"intact": 0, "merged": 0, "own": 0}

    def description(
        a: str, b: str, pmid: str, method_class: str, psimi_id: str, **ids: str
    ) -> Description:
        return Description(
            interaction_id=interaction_id(a, b),
            kind=InteractionKind.HH.value,
            side_a=a,
            side_b=b,
            pmid=pmid,
            method_id=psimi_id,
            method_name=name_of(psimi_id),
            method_class=method_class,
            **ids,
        )

    for (a, b, pmid, method_class), found in files.groups(files.read(merged), 4):
        intact = [r for r in found if r[4] == INTACT]
        ours = [r[8] for r in found if r[4] == CURATED]
        for position, record in enumerate(intact):
            intact_id, psimi_id = record[6], record[7]
            if position and intact_id == intact[position - 1][6]:
                raise LoadError(f"intact.tsv: {intact_id} {a} {b} appears twice")
            row = description(
                a,
                b,
                pmid,
                method_class,
                psimi_id,
                id=intact_description_id(intact_id, a, b),
                intact_id=intact_id,
                stable_ids=";".join(ours) if position == 0 else "",
            )
            out.write("\t".join(row) + "\n")
        counts["intact"] += len(intact)
        if intact:
            counts["merged"] += len(ours)
            continue
        counts["own"] += len(ours)
        for record in (r for r in found if r[4] == CURATED):
            row = description(
                a,
                b,
                pmid,
                method_class,
                record[7],
                id=record[8],
                intact_id="",
                stable_ids=record[8],
            )
            out.write("\t".join(row) + "\n")
    logger.info(
        "%d HH: %d IntAct descriptions; %d curated rows are IntAct's, %d are not",
        host.taxon_id,
        counts["intact"],
        counts["merged"],
        counts["own"],
    )
