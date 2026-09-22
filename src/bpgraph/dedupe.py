"""Collapsing an export's repeated records before they reach the graph."""

from collections.abc import Callable, Hashable, Iterable


class ConflictingRecords(ValueError):
    """Two records share a key but disagree on their contents."""


def dedupe[T](records: Iterable[T], key: Callable[[T], Hashable]) -> list[T]:
    """Keep one record per key, preserving order.

    A build writes with `CREATE`, so anything repeated in the export would
    become a duplicate node. Collapsing here is what makes that safe — and two
    records that share a key while disagreeing are an export bug, surfaced now
    rather than as a constraint failure at the end of the run.
    """
    seen: dict[Hashable, T] = {}
    for record in records:
        identity = key(record)
        previous = seen.get(identity)
        if previous is None:
            seen[identity] = record
        elif previous != record:
            raise ConflictingRecords(
                f"{identity!r} appears twice with different contents"
            )
    return list(seen.values())
