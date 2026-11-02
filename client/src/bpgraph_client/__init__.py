"""The commands of the skills that consult bpgraph.

`bpgraph-client COMMAND ARGUMENTS` runs one command, and
`bpgraph-client COMMAND --help` says what it does. None reaches the graph: the
skills query it through the MCP server's tools, and a command does the
mechanical part on what they gathered.
"""

import argparse
from collections.abc import Mapping
from typing import Protocol

from bpgraph_client import render


class Command(Protocol):
    """A module that is a command: its docstring is its `--help`, the first
    line of it what `bpgraph-client --help` lists."""

    def arguments(self, parser: argparse.ArgumentParser) -> None: ...

    def run(self, args: argparse.Namespace) -> None: ...


COMMANDS: Mapping[str, Command] = {"render": render}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for name, command in COMMANDS.items():
        doc = command.__doc__ or ""
        command.arguments(
            commands.add_parser(
                name,
                description=doc,
                help=doc.partition("\n")[0],
                formatter_class=argparse.RawDescriptionHelpFormatter,
            )
        )
    args = parser.parse_args()
    command: Command = COMMANDS[args.command]
    command.run(args)
