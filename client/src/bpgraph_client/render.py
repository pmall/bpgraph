"""Draw a network: a `network.json` in, a fixed page out.

`bpgraph-client render NETWORK` reads `<name>.json`, a `Network`, refusing a
file that breaks its rules, and writes `<name>.cytoscape.html` beside it from
the `cytoscape.html` template shipped with this package. It prints the counts
of proteins and interactions, and the page's path.

Choosing what a network holds is judgment, and belongs to whoever gathers it —
usually an agent following the `network-view` skill, querying the live graph.
Drawing it is not: every network goes through the same file format and
the same renderer, so two networks made a month apart look alike and compare
directly. Rendering needs no database, only the file.

The page is a standard starting point. Its layout is force-directed, fcose, and
its proteins are circles labelled with their name: viral proteins red, human
proteins with a viral partner blue, the others grey. An edge is as wide as its
`n_publications`. Clicking a protein or an interaction shows its details,
proteins can be dragged, and Save PNG saves the whole network as it stands, at
3× resolution, as `<name>.png`. The page's `adjust` block, described where it
sits, is where colours, labels, shapes and layout get changed afterwards,
leaving the rest of the page alone. Rendering again overwrites the page,
adjustments included.
"""

import argparse
import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NetworkProtein(Model):
    """A protein the network draws."""

    id: str
    """Names the protein within the file, once: a human protein's accession, a
    viral protein's virus taxon id and name joined by `:`, `3052230:NS5A`."""
    name: str
    """Its label: a human protein's gene symbol, a viral protein's name."""
    kind: Literal["human", "viral"]
    description: str
    """UniProt's name for a human protein, empty for a viral one."""
    taxon_name: str
    """A viral protein's virus, as the graph's `:Virus` names it, `Hepatitis C
    virus`; `Homo sapiens` for a human one."""
    attributes: Mapping[str, str | int | float | bool] = {}
    """Whatever else the network records about a protein, such as a topic's
    `role` or the viral family. Shown when the protein is clicked, and
    selectable when adjusting the page's style."""


class NetworkInteraction(Model):
    """An interaction between two proteins of the network."""

    source: str
    """The `id` of one of its proteins."""
    target: str
    """The `id` of the other."""
    n_publications: int
    """The interaction's counter, as the graph holds it."""
    n_methods: int
    """The interaction's counter, as the graph holds it."""


class Network(Model):
    """What a renderer draws, and everything it draws from: `network.json`.
    A protein's `id` is listed once, and an interaction joins two listed
    proteins, each pair once, whichever way round."""

    title: str
    """The page's title, `Ferroptosis × Flaviviridae (golden)`."""
    description: str
    """Shown under the title: what is drawn, and the evidence level applied."""
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


def draw(path: Path) -> Path:
    """Write the page of the network at `path` beside it, and return it."""
    network = Network.model_validate_json(path.read_text())
    template = Path(__file__).with_name("cytoscape.html").read_text()
    page = path.with_name(f"{path.stem}.cytoscape.html")
    page.write_text(render(network, template))
    print(
        f"{len(network.proteins)} proteins, {len(network.interactions)} interactions\n"
        f"{page}"
    )
    return page


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("network", type=Path, metavar="NETWORK")


def run(args: argparse.Namespace) -> None:
    network: Path = args.network
    draw(network)
