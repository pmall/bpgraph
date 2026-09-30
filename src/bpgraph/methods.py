"""The curated methods: for every PSI-MI detection method, whether IntAct keeps
it.

`curation/methods.tsv` has one row per detection method (`MI:0001` and below)
and says `yes` or `no`: whether an IntAct row with that method enters the
graph, as evidence of a real interaction, observed by an experiment. Our
curated descriptions are kept whatever their method. `curation/methods.md`
says where the flags come from and what `no` means.

A detection method without a row fails the IntAct fetch, as an uncurated viral
taxon fails the build: a new PSI-MI term is always a decision someone made.
"""

import csv
import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from bpgraph.psimi import Ontology, read_ontology
from bpgraph.run import Run

logger = logging.getLogger(__name__)

CURATED = Path(__file__).resolve().parents[2] / "curation" / "methods.tsv"
COLUMNS = ("psimi_id", "name", "keep")
KEEP = {"yes": True, "no": False}

DETECTION = "MI:0001"
"""Interaction detection method: every term below it must have a row."""


class UncuratedMethods(ValueError):
    """Detection methods without a row in `methods.tsv`. Add them."""


@dataclass(frozen=True, slots=True)
class Method:
    psimi_id: str
    name: str
    keep: bool


def read_methods(path: Path = CURATED) -> list[Method]:
    """The rows of the list. Each term is listed once, `yes` or `no`."""
    methods: list[Method] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        for line, row in enumerate(reader, start=2):
            keep = row["keep"].strip()
            if keep not in KEEP:
                raise ValueError(f"{path.name}:{line}: keep is yes or no")
            methods.append(
                Method(
                    psimi_id=row["psimi_id"].strip(),
                    name=row["name"].strip(),
                    keep=KEEP[keep],
                )
            )
    counts = Counter(m.psimi_id for m in methods)
    repeated = [term for term, n in counts.items() if n > 1]
    if repeated:
        raise ValueError(f"{path.name}: psimi_id repeats: {sorted(repeated)}")
    return methods


@dataclass(frozen=True, slots=True)
class Methods:
    """The list, checked against PSI-MI: every row a current detection method,
    every current detection method a row."""

    ontology: Ontology
    rows: Mapping[str, Method]

    @classmethod
    def load(cls, ontology: Ontology, path: Path = CURATED) -> Self:
        methods = read_methods(path)
        unknown = [
            m.psimi_id
            for m in methods
            if ontology.canonical(m.psimi_id) != m.psimi_id
            or not ontology.under(m.psimi_id, (DETECTION,))
        ]
        if unknown:
            raise ValueError(
                f"{path.name}: not current PSI-MI detection methods: {sorted(unknown)}"
            )
        for method in methods:
            name = ontology.terms[method.psimi_id].name
            if method.name != name:
                logger.warning(
                    "%s: %s is now named %r in PSI-MI; update %s",
                    method.name,
                    method.psimi_id,
                    name,
                    path.name,
                )
        loaded = cls(ontology=ontology, rows={m.psimi_id: m for m in methods})
        loaded.check(
            term
            for term, info in ontology.terms.items()
            if not info.obsolete and ontology.under(term, (DETECTION,))
        )
        return loaded

    def keep(self, psimi_id: str) -> bool | None:
        """Whether IntAct keeps a term, or nothing if it has no row."""
        method = self.rows.get(psimi_id)
        return method.keep if method else None

    def check(self, psimi_ids: Iterable[str]) -> None:
        """`UncuratedMethods` naming the terms without a row, if any."""
        failing = [
            f"{psimi_id} {term.name if term else '?'}"
            for psimi_id in sorted(set(psimi_ids))
            if psimi_id not in self.rows
            for term in (self.ontology.terms.get(psimi_id),)
        ]
        if failing:
            raise UncuratedMethods(
                "no row in methods.tsv for:\n  " + "\n  ".join(failing)
            )


def main() -> None:
    """Check `curation/methods.tsv` against one run's PSI-MI.

    `uv run bpgraph-methods data/2026-09-09` fails naming the detection methods
    without a row, or the rows that are not current detection methods, and
    otherwise prints how many are kept.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-methods <run directory>")
    run = Run(Path(sys.argv[1]))
    try:
        methods = Methods.load(read_ontology(run.psimi))
    except ValueError as error:
        sys.exit(str(error))
    kept = sum(m.keep for m in methods.rows.values())
    print(f"{len(methods.rows)} detection methods: {kept} kept")
