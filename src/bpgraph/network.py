"""Draw a network: a `network.json` in, a fixed page out.

Choosing what a network holds is judgment, and belongs to whoever gathers it —
usually an agent following the `network-view` skill, querying the live graph.
Drawing it is not: every network goes through the same file format and
the same renderer, so two networks made a month apart look alike and compare
directly. Rendering needs no database, only the file.

`bpgraph-network <name>.json` writes `<name>.cytoscape.html` beside it. The
page is a standard starting point: its `adjust` block is where colours, labels,
shapes and layout get changed afterwards, leaving the rest of the page alone.
"""

import html
import sys
from collections.abc import Mapping, Sequence
from importlib.resources import files
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NetworkProtein(Model):
    id: str
    name: str
    kind: Literal["human", "viral"]
    description: str
    taxon_name: str
    attributes: Mapping[str, str | int | float | bool] = {}
    """Whatever else the network records about a protein, e.g. a topic's
    `role`. Shown on the page, and selectable when adjusting its style."""


class NetworkInteraction(Model):
    source: str
    target: str
    n_publications: int
    n_methods: int


class Network(Model):
    """What a renderer draws, and everything it draws from."""

    title: str
    description: str
    proteins: Sequence[NetworkProtein]
    interactions: Sequence[NetworkInteraction]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [protein.id for protein in self.proteins]
        if len(set(ids)) != len(ids):
            raise ValueError("protein ids repeat")
        known = set(ids)
        pairs: set[frozenset[str]] = set()
        for interaction in self.interactions:
            ends = (interaction.source, interaction.target)
            for end in ends:
                if end not in known:
                    raise ValueError(f"interaction names unknown protein {end!r}")
            if frozenset(ends) in pairs:
                raise ValueError(f"interaction {ends} repeats")
            pairs.add(frozenset(ends))
        return self


def render(network: Network, template: str) -> str:
    """Fill a renderer template with the network. The JSON sits in a
    `<script>` element, so `</` is escaped to keep it from closing one."""
    data = network.model_dump_json().replace("</", "<\\/")
    title = html.escape(network.title)
    return template.replace("{{title}}", title).replace("{{network}}", data)


def main() -> None:
    """`bpgraph-network <network.json>`: draw it with Cytoscape."""
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-network <network.json>")
    path = Path(sys.argv[1])
    network = Network.model_validate_json(path.read_text())
    template = files("bpgraph").joinpath("templates/cytoscape.html").read_text()
    page = path.with_name(f"{path.stem}.cytoscape.html")
    page.write_text(render(network, template))
    print(
        f"{len(network.proteins)} proteins, {len(network.interactions)} interactions\n"
        f"{page}"
    )
