"""Turning a source export into an `Export`.

A loader parses files and returns models; it never touches the database. That
line is what keeps source quirks out of the graph layer — if a source encodes
coordinates differently, or names a method by a synonym, it is normalized here
and the writers never learn about it.

`TsvExport` reads the tab-separated export documented in docs/export.md. Any
other source does the same thing: produce an `Export`, and hand it to
`bpgraph.build.build`.
"""

from bpgraph.loaders.tsv import TsvExport

__all__ = ["TsvExport"]
