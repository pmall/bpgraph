"""The commands of the skills that consult bpgraph.

`bpgraph-client <command> <arguments>`, each command described in its module's
docstring:

- `render`: draw a network, `<name>.json` in, `<name>.cytoscape.html` out.

None reaches the graph: the skills query it through the MCP server's tools, and
a command does the mechanical part on what they gathered.
"""

import sys
from collections.abc import Callable, Mapping, Sequence

from bpgraph_client import render

COMMANDS: Mapping[str, Callable[[Sequence[str]], None]] = {"render": render.main}


def main() -> None:
    """`bpgraph-client <command> <arguments>`: run one command."""
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        sys.exit(f"usage: bpgraph-client {{{','.join(COMMANDS)}}} <arguments>")
    COMMANDS[sys.argv[1]](sys.argv[2:])
