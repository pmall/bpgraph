"""Closed vocabularies shared by the models, the ids and the writers."""

from enum import StrEnum


class ProteinKind(StrEnum):
    """Which label a protein node carries beside `:Protein`."""

    HUMAN = "h"
    VIRAL = "v"


class TaxonKind(StrEnum):
    """The second label on a taxon node: a curated virus, or its family."""

    VIRUS = "Virus"
    FAMILY = "Family"


class InteractionKind(StrEnum):
    """The second label on an interaction node. Human-human or virus-human."""

    HH = "HH"
    VH = "VH"


class Side(StrEnum):
    """Which slot of an interaction a partner occupies. `A` is always human."""

    A = "a"
    B = "b"


class GoNamespace(StrEnum):
    BIOLOGICAL_PROCESS = "biological_process"
    MOLECULAR_FUNCTION = "molecular_function"
    CELLULAR_COMPONENT = "cellular_component"


class GoRelation(StrEnum):
    """The two GO edges the true path rule holds over."""

    IS_A = "IS_A"
    PART_OF = "PART_OF"
