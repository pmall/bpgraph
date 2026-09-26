"""Turning a run directory into a `Snapshot` and its vaults.

A loader parses files and returns models; it never touches the database. That
line is what keeps source quirks out of the graph layer — if a source encodes
coordinates differently, or names a method by a synonym, it is normalized here
and the writers never learn about it.

A silo has a loader of its own: `host` for a host species, `viral` for our
virus–host interactions; `export` reads the curation export both draw on, and
`run` puts the silos together.
"""

from bpgraph.loaders.run import Loaded, RunLoader

__all__ = ["Loaded", "RunLoader"]
