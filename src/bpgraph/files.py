"""Intermediate files, sorted on disk and read side by side.

Nothing a build or a fetch reads is ever held whole in memory. Where rows of
two files have to meet — a curated row and the IntAct row it merges onto, a
peptide and its description — both are written to an intermediate file with
the shared key in their leading fields, sorted on disk by GNU `sort`, and read
back side by side: memory holds one group of rows sharing a key, never a file.

An intermediate file is tab-separated and has no header; a field is known by
its position. It is sorted by the whole line, in byte order. A tab sorts below
every character a field may hold, so that is the order of the fields from the
first one on, which is also how Python compares tuples of `str`.
"""

import os
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from itertools import groupby
from pathlib import Path

type Record = list[str]
type Key = tuple[str, ...]

SORT_MEMORY = "256M"
"""What `sort` may use before it spills to disk."""


def write(path: Path, records: Iterable[Sequence[str]]) -> int:
    """Write records, one per line. Returns how many."""
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write("\t".join(record) + "\n")
            written += 1
    return written


def write_table(
    path: Path, header: Sequence[str], records: Iterable[Sequence[str]]
) -> int:
    """Write a file a run keeps: a header row, then the records. Returns how
    many records."""
    written = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(header) + "\n")
        for record in records:
            handle.write("\t".join(record) + "\n")
            written += 1
    return written


def read(path: Path) -> Iterator[Record]:
    with path.open(encoding="utf-8", newline="\n") as handle:
        for line in handle:
            yield line.rstrip("\n").split("\t")


def sort(path: Path, unique: bool = False) -> Path:
    """Sort a file in place, on disk. `unique` drops repeated lines."""
    command = ["sort", "-S", SORT_MEMORY, "-T", str(path.parent), "-o", str(path)]
    if unique:
        command.append("-u")
    subprocess.run([*command, str(path)], check=True, env={**os.environ, "LC_ALL": "C"})
    return path


def sorted_file(
    path: Path, records: Iterable[Sequence[str]], unique: bool = False
) -> Path:
    """Write records and sort them: the leading fields are the key."""
    write(path, records)
    return sort(path, unique)


def groups(records: Iterable[Record], width: int) -> Iterator[tuple[Key, list[Record]]]:
    """Consecutive records sharing their first `width` fields."""
    for key, group in groupby(records, key=lambda record: tuple(record[:width])):
        yield key, list(group)


def cogroup(
    left: Iterable[Record], right: Iterable[Record], width: int
) -> Iterator[tuple[Key, list[Record], list[Record]]]:
    """Two files sorted on their first `width` fields, read side by side: each
    key once, with the records either side holds for it, possibly none."""
    lefts, rights = groups(left, width), groups(right, width)
    this, that = next(lefts, None), next(rights, None)
    while this is not None or that is not None:
        if that is None or (this is not None and this[0] < that[0]):
            assert this is not None
            yield this[0], this[1], []
            this = next(lefts, None)
        elif this is None or that[0] < this[0]:
            yield that[0], [], that[1]
            that = next(rights, None)
        else:
            yield this[0], this[1], that[1]
            this, that = next(lefts, None), next(rights, None)
