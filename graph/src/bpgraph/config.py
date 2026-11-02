"""Connection settings, read from the environment: the FalkorDB server at
`FALKORDB_HOST` and `FALKORDB_PORT` (`localhost:6379` by default), with
`FALKORDB_PASSWORD`, empty for a server without auth, and the live graph's
vaults in `BPGRAPH_VAULT` (`data/vault` by default)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Self

LIVE_GRAPH = "bpgraph"
STAGING_GRAPH = "bpgraph_staging"
LIVE_VAULT = Path("data/vault")
"""Where a build publishes the vaults of the live graph, and the API reads them."""


@dataclass(frozen=True, slots=True)
class Config:
    host: str = "localhost"
    port: int = 6379
    password: str = ""
    live_graph: str = LIVE_GRAPH
    staging_graph: str = STAGING_GRAPH
    vault: Path = LIVE_VAULT

    @classmethod
    def from_env(cls) -> Self:
        """Read the variables, the same docker-compose.yml sets."""
        return cls(
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            password=os.environ.get("FALKORDB_PASSWORD", ""),
            vault=Path(os.environ.get("BPGRAPH_VAULT", str(LIVE_VAULT))),
        )
