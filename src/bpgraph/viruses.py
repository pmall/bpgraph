"""The curated viruses viral proteins are grouped by.

`curation/viruses.tsv` names one virus per row — `HBV`, `SARS-CoV-2`, `IAV` —
anchored at an NCBI taxon; `curation/NAMING.md` says why each row is what it
is. A viral protein belongs to the **most specific** row enclosing its own
taxon, so strains and isolates roll up to their virus without being listed.

A taxon no row encloses fails the build. Falling back to an NCBI rank would
quietly put a protein under a name nobody chose.
"""

import csv
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from bpgraph.models import Virus
from bpgraph.taxonomy import Taxonomy

logger = logging.getLogger(__name__)

CURATED = Path(__file__).resolve().parents[2] / "curation" / "viruses.tsv"
COLUMNS = ("taxon_id", "name", "full_name")


class UncuratedTaxa(ValueError):
    """Viral taxa no curated virus encloses. Add rows to `viruses.tsv`."""


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
    """The list, placed on the taxonomy so a taxon finds its virus by interval."""

    taxonomy: Taxonomy
    viruses: Mapping[int, Virus]
    bounds: tuple[tuple[int, int, int], ...]
    """`(lft, rgt, taxon_id)` per virus, the nested-set interval of its taxon."""

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
                virus = virus.model_copy(update={"taxon_id": current})
            viruses[current] = virus
        bounds = tuple((*taxonomy.interval(taxon_id), taxon_id) for taxon_id in viruses)
        return cls(taxonomy=taxonomy, viruses=viruses, bounds=bounds)

    def enclosing(self, taxon_id: int) -> Virus | None:
        """The most specific curated virus enclosing a taxon, if any does."""
        lft, rgt = self.taxonomy.interval(taxon_id)
        best: tuple[int, int] | None = None
        for left, right, virus_id in self.bounds:
            if left <= lft and rgt <= right and (best is None or left > best[0]):
                best = (left, virus_id)
        return None if best is None else self.viruses[best[1]]

    def require(self, taxon_ids: Iterable[int]) -> None:
        """Fail naming every taxon no curated virus encloses."""
        missing = sorted(
            {taxon_id for taxon_id in taxon_ids if self.enclosing(taxon_id) is None}
        )
        if missing:
            named = ", ".join(
                f"{taxon_id} {self.taxonomy.name(taxon_id)!r}" for taxon_id in missing
            )
            raise UncuratedTaxa(
                f"{len(missing)} viral taxa have no curated virus in "
                f"{CURATED.name}: {named}"
            )
