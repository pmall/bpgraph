"""A graph of protein-protein interactions, their evidence and their context."""

from bpgraph.build import BuildReport, build
from bpgraph.client import GraphWriter, connect
from bpgraph.config import Config
from bpgraph.models import Export

__all__ = ["BuildReport", "Config", "Export", "GraphWriter", "build", "connect"]


def main() -> None:
    """Report what the live graph currently holds."""
    config = Config.from_env()
    db = connect(config)
    if config.live_graph not in db.list_graphs():
        print(f"{config.live_graph}: not built yet")
        return
    graph = db.select_graph(config.live_graph)
    for label in ("Protein", "Interaction", "Description", "Peptide", "Publication"):
        result = graph.ro_query(f"MATCH (n:{label}) RETURN count(n)").result_set
        print(f"{label:<12} {result[0][0]:>9,}")
