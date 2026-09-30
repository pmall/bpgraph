"""Connection settings, read from the environment."""

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
        """Read the same variables docker-compose.yml uses. An empty password
        means the server runs without auth, which is the local default."""
        return cls(
            host=os.environ.get("FALKORDB_HOST", "localhost"),
            port=int(os.environ.get("FALKORDB_PORT", "6379")),
            password=os.environ.get("FALKORDB_PASSWORD", ""),
            vault=Path(os.environ.get("BPGRAPH_VAULT", str(LIVE_VAULT))),
        )
