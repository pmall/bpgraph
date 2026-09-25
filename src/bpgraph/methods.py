"""The curated method classes: which detection methods count as one.

`curation/methods.tsv` names one class root per row — a PSI-MI term, standing
for itself and every term below it. A method takes the class of the **most
specific** row enclosing it, so PSI-MI's many names for one technique fall
under the class of the term they share. `curation/methods.md` says why each
row is what it is.

A method no row encloses fails the build, as an uncurated viral taxon does;
so does one two rows enclose with neither below the other, when they disagree
on its class. PSI-MI is a DAG, and such a term needs a row of its own.
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
COLUMNS = ("psimi_id", "name", "class")

ROOT = "MI:0000"
"""The root of PSI-MI, which the export uses as a placeholder on a stray row. It
says nothing about the method, and a row for it would enclose every term and
turn the gate off, so a description coded with it is dropped instead."""


class UncuratedMethods(ValueError):
    """Methods no curated row encloses, or that two rows disagree on. Add rows
    to `methods.tsv`."""


@dataclass(frozen=True, slots=True)
class ClassRoot:
    psimi_id: str
    name: str
    method_class: str


def read_methods(path: Path = CURATED) -> list[ClassRoot]:
    """The rows of the list. Each term is a root once."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        roots = [
            ClassRoot(
                psimi_id=row["psimi_id"].strip(),
                name=row["name"].strip(),
                method_class=row["class"].strip(),
            )
            for row in reader
        ]
    repeated = [term for term, n in Counter(r.psimi_id for r in roots).items() if n > 1]
    if repeated:
        raise ValueError(f"{path.name}: psimi_id repeats: {sorted(repeated)}")
    return roots


@dataclass(frozen=True, slots=True)
class MethodClasses:
    """The list, placed on PSI-MI."""

    ontology: Ontology
    roots: Mapping[str, ClassRoot]

    @classmethod
    def load(cls, ontology: Ontology, path: Path = CURATED) -> Self:
        roots = read_methods(path)
        unknown = [
            r.psimi_id for r in roots if ontology.canonical(r.psimi_id) != r.psimi_id
        ]
        if unknown:
            raise ValueError(
                f"{path.name}: not current PSI-MI terms: {sorted(unknown)}"
            )
        for root in roots:
            name = ontology.terms[root.psimi_id].name
            if root.name != name:
                logger.warning(
                    "%s: %s is now named %r in PSI-MI; update %s",
                    root.name,
                    root.psimi_id,
                    name,
                    path.name,
                )
        return cls(ontology=ontology, roots={root.psimi_id: root for root in roots})

    def enclosing(self, psimi_id: str) -> tuple[ClassRoot, ...]:
        """The most specific rows enclosing a term: those no other enclosing
        row sits below."""
        enclosing = {
            term for term in self.ontology.ancestors(psimi_id) if term in self.roots
        }
        closest = [
            term
            for term in enclosing
            if not any(
                other != term and term in self.ontology.ancestors(other)
                for other in enclosing
            )
        ]
        return tuple(self.roots[term] for term in sorted(closest))

    def class_of(self, psimi_id: str) -> str | None:
        """A term's class, or nothing if no row, or no agreement, gives one."""
        classes = {root.method_class for root in self.enclosing(psimi_id)}
        return classes.pop() if len(classes) == 1 else None

    def resolve(self, psimi_ids: Iterable[str]) -> dict[str, str]:
        """Every term's class, or `UncuratedMethods` naming those without one."""
        resolved: dict[str, str] = {}
        failing: list[str] = []
        for psimi_id in sorted(set(psimi_ids)):
            method_class = self.class_of(psimi_id)
            if method_class is None:
                name = (
                    self.ontology.terms[psimi_id].name
                    if psimi_id in self.ontology.terms
                    else "?"
                )
                roots = (
                    ", ".join(r.psimi_id for r in self.enclosing(psimi_id)) or "none"
                )
                failing.append(f"{psimi_id} {name} (enclosed by: {roots})")
            else:
                resolved[psimi_id] = method_class
        if failing:
            raise UncuratedMethods(
                "no single curated class for:\n  " + "\n  ".join(failing)
            )
        return resolved


def main() -> None:
    """Check the curation against one run: every method of its export and of
    its IntAct must have a class.

    `uv run bpgraph-methods data/2026-09-09` prints each class with the terms
    it holds and how many rows of each source use them, or the terms to add.
    """
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-methods <run directory>")
    run = Run(Path(sys.argv[1]))
    ontology = read_ontology(run.psimi)
    counts: dict[str, Counter[str]] = {"export": Counter(), "intact": Counter()}
    for source, path in (
        ("export", run.export / "descriptions.tsv"),
        ("intact", run.intact),
    ):
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
            for row in reader:
                counts[source][row["psimi_id"]] += 1
    classes = MethodClasses.load(ontology)
    used = (set(counts["export"]) | set(counts["intact"])) - {ROOT}
    by_class: dict[str, list[str]] = {}
    for psimi_id in used:
        method_class = classes.class_of(psimi_id)
        if method_class is not None:
            by_class.setdefault(method_class, []).append(psimi_id)
    totals = {
        c: (sum(counts["export"][t] for t in ts), sum(counts["intact"][t] for t in ts))
        for c, ts in by_class.items()
    }
    for method_class in sorted(by_class, key=lambda c: -sum(totals[c])):
        export, intact = totals[method_class]
        print(f"{method_class}  export={export} intact={intact}")
        for psimi_id in sorted(
            by_class[method_class],
            key=lambda t: -counts["export"][t] - counts["intact"][t],
        ):
            export, intact = counts["export"][psimi_id], counts["intact"][psimi_id]
            name = ontology.terms[psimi_id].name
            print(f"    {psimi_id} {name}  export={export} intact={intact}")
    print(f"{sum(map(len, by_class.values()))} terms in {len(by_class)} classes")
    dropped = counts["export"][ROOT] + counts["intact"][ROOT]
    if dropped:
        print(f"{dropped} rows coded {ROOT} are dropped")
    try:
        classes.resolve(used)
    except UncuratedMethods as error:
        sys.exit(str(error))
