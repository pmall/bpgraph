"""The curated viruses viral proteins are grouped by.

`curation/viruses.tsv` names one virus per row — `HBV`, `SARS-CoV-2`, `IAV` —
anchored at an NCBI taxon; `curation/viruses.md` says why each row is what it
is. A viral protein belongs to the **most specific** row enclosing its own
taxon, so strains and isolates roll up to their virus without being listed.

A taxon no row encloses fails the build. Falling back to an NCBI rank would
quietly put a protein under a name nobody chose.
"""

import csv
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Self

from bpgraph.taxonomy import Taxonomy

logger = logging.getLogger(__name__)

CURATED = Path(__file__).resolve().parents[2] / "curation" / "viruses.tsv"
COLUMNS = ("taxon_id", "name", "full_name")


class UncuratedTaxa(ValueError):
    """Viral taxa no curated virus encloses. Add rows to `viruses.tsv`."""


@dataclass(frozen=True, slots=True)
class Virus:
    """A curated virus: `HBV`, `SARS-CoV-2`."""

    taxon_id: int
    name: str
    full_name: str


def read_viruses(path: Path = CURATED) -> list[Virus]:
    """The rows of the list. Ids and names are each unique."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        viruses = [
            Virus(
                taxon_id=int(row["taxon_id"]),
                name=row["name"].strip(),
                full_name=row["full_name"].strip(),
            )
            for row in reader
        ]
    for attribute in ("taxon_id", "name"):
        values = [getattr(virus, attribute) for virus in viruses]
        repeated = {value for value in values if values.count(value) > 1}
        if repeated:
            raise ValueError(f"{path.name}: {attribute} repeats: {sorted(repeated)}")
    return viruses


@dataclass(frozen=True, slots=True)
class CuratedViruses:
    """The list, placed on the taxonomy."""

    taxonomy: Taxonomy
    viruses: Mapping[int, Virus]

    @classmethod
    def load(cls, taxonomy: Taxonomy, path: Path = CURATED) -> Self:
        viruses: dict[int, Virus] = {}
        for virus in read_viruses(path):
            current = taxonomy.canonical(virus.taxon_id)
            if current != virus.taxon_id:
                logger.warning(
                    "%s: taxon %d is now %d in NCBI; update %s",
                    virus.name,
                    virus.taxon_id,
                    current,
                    path.name,
                )
                virus = replace(virus, taxon_id=current)
            viruses[current] = virus
        return cls(taxonomy=taxonomy, viruses=viruses)

    def enclosing(self, taxon_id: int) -> Virus | None:
        """The most specific curated virus enclosing a taxon, if any does: the
        first one met walking up from it."""
        return next(
            (
                self.viruses[taxon.taxon_id]
                for taxon in self.taxonomy.lineage(taxon_id)
                if taxon.taxon_id in self.viruses
            ),
            None,
        )
