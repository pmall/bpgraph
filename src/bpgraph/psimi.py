"""The PSI-MI ontology: what a method's `psimi_id` is called, and what it is under.

Every method name the graph holds comes from here, not from the export or
IntAct, which each carry their own copy of the name. The hierarchy serves two
readers: the IntAct filter, which drops a method or an interaction type by the
branch it sits in, and the method classes of `bpgraph.methods`, which a term
takes from the closest curated term above it.

PSI-MI is a DAG over `is_a` alone; the file has no other relation. A retired
term keeps its id and name but loses its parents, so it sits under nothing.
"""

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast
from urllib.request import Request, urlopen

from bpgraph.go import download
from bpgraph.obo import TERM, stanzas, target
from bpgraph.run import Run
from bpgraph.sources import record_source

logger = logging.getLogger(__name__)

URL = "https://raw.githubusercontent.com/HUPO-PSI/psi-mi-CV/master/psi-mi.obo"
COMMITS_URL = (
    "https://api.github.com/repos/HUPO-PSI/psi-mi-CV/commits?path=psi-mi.obo&per_page=1"
)
"""The file names no release of its own — its `date` header is years stale — so
the release is the repository's last commit to it."""

IS_A = "is_a"
ALT_ID = "alt_id"
OBSOLETE = "is_obsolete"
TRUE = "true"


class _Author(TypedDict):
    date: str


class _Commit(TypedDict):
    author: _Author


class _Entry(TypedDict):
    sha: str
    commit: _Commit


@dataclass(frozen=True, slots=True)
class Term:
    psimi_id: str
    name: str
    obsolete: bool


@dataclass(frozen=True, slots=True)
class Ontology:
    """`psi-mi.obo`, reduced to terms and their `is_a` parents.

    `aliases` maps the few secondary ids PSI-MI keeps onto the primary one.
    """

    terms: Mapping[str, Term]
    parents: Mapping[str, tuple[str, ...]]
    aliases: Mapping[str, str]

    def canonical(self, psimi_id: str) -> str | None:
        """The id this term is known by now, or nothing if PSI-MI never had it."""
        if psimi_id in self.terms:
            return psimi_id
        return self.aliases.get(psimi_id)

    def ancestors(self, psimi_id: str) -> frozenset[str]:
        """The term and everything above it."""
        reached: set[str] = set()
        frontier = [psimi_id]
        while frontier:
            current = frontier.pop()
            if current in reached:
                continue
            reached.add(current)
            frontier.extend(self.parents.get(current, ()))
        return frozenset(reached)

    def under(self, psimi_id: str, roots: Iterable[str]) -> bool:
        """Whether a term is one of these roots or sits below one of them."""
        return not self.ancestors(psimi_id).isdisjoint(roots)


def read_ontology(path: Path) -> Ontology:
    """Parse `psi-mi.obo`. Terms only; the typedefs describe the relation."""
    terms: dict[str, Term] = {}
    parents: dict[str, tuple[str, ...]] = {}
    aliases: dict[str, str] = {}
    for heading, fields in stanzas(path):
        if heading != TERM:
            continue
        psimi_id = fields["id"][0]
        terms[psimi_id] = Term(
            psimi_id=psimi_id,
            name=" ".join(fields["name"][0].split()),
            obsolete=fields.get(OBSOLETE, ())[:1] == [TRUE],
        )
        parents[psimi_id] = tuple(target(parent) for parent in fields.get(IS_A, ()))
        for alias in fields.get(ALT_ID, ()):
            aliases[alias] = psimi_id
    logger.info("psi-mi: %d terms in %s", len(terms), path)
    return Ontology(terms=terms, parents=parents, aliases=aliases)


def _release() -> str:
    """The date and commit of the file's last change on GitHub."""
    request = Request(COMMITS_URL, headers={"User-Agent": "bpgraph"})
    with urlopen(request) as response:
        entry = cast(list[_Entry], json.load(response))[0]
    return f"{entry['commit']['author']['date'][:10]} {entry['sha'][:7]}"


def fetch(run: Run) -> Path:
    """Download the ontology into a run directory, unless it is there already."""
    if not run.psimi.exists():
        logger.info("psi-mi: fetching %s", URL)
        release = _release()
        download(URL, run.psimi)
        record_source(run.sources, "psi-mi", URL, release)
    return run.psimi


def main() -> None:
    """Fetch PSI-MI into one run directory.

    `uv run bpgraph-psimi data/2026-09-09` writes `psi-mi.obo` beside the export
    and records the fetch.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-psimi <run directory>")
    path = fetch(Run(Path(sys.argv[1])))
    print(f"{path}: {len(read_ontology(path).terms)} terms")
