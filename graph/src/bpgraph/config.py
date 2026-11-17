"""Connection settings, read from the environment: the FalkorDB server at
`FALKORDB_HOST` and `FALKORDB_PORT` (`localhost:6379` by default), with
`FALKORDB_PASSWORD`, empty for a server without auth, and the data directory
in `BPGRAPH_DATA`, which holds the runs and, in `vault/`, the live graph's
vaults. It has no default: it lies outside the repository."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

LIVE_GRAPH = "bpgraph"
STAGING_GRAPH = "bpgraph_staging"


@dataclass(frozen=True, slots=True)
class Config:
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    live_graph: str = LIVE_GRAPH
    staging_graph: str = STAGING_GRAPH

    @classmethod
    def from_env(cls) -> Self:
        """Read the variables, the same docker-compose.yml sets."""
        return cls(
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            password=os.environ.get("FALKORDB_PASSWORD", ""),
        )


def live_vault() -> Path:
    """Where a build publishes the vaults of the live graph, and the API reads
    them: `vault/` in the data directory, `BPGRAPH_DATA`."""
    data = os.environ.get("BPGRAPH_DATA")
    if not data:
        raise SystemExit("BPGRAPH_DATA is not set: the data directory, as .env says")
    return Path(data) / "vault"
