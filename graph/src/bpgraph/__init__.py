"""A graph of protein-protein interactions, their evidence and their context.

`bpgraph` reports what the live graph holds: its nodes of each kind, counted, or
that it is not built yet. The package's other commands build the graph and
serve it, and each one's `--help` says what it does.
"""

import argparse

from bpgraph.client import connect, exists
from bpgraph.config import Config


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    ).parse_args()
    config = Config.from_env()
    db = connect(config)
    if not exists(db, config.live_graph):
        print(f"{config.live_graph}: not built yet")
        return
    graph = db.select_graph(config.live_graph)
    labels = (
        "Protein",
        "Interaction",
        "Description",
        "Annotation",
        "Peptide",
        "Publication",
    )
    for label in labels:
        result = graph.ro_query(f"MATCH (n:{label}) RETURN count(n)").result_set
        print(f"{label:<12} {result[0][0]:>9,}")
