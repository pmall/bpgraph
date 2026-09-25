"""The only place a bpgraph identifier is constructed.

Two labels need a derived id because their natural key is several values at
once; every other label keys on a value that comes straight from the data. See
docs/schema.md section 3.
"""


def human_protein_id(accession: str) -> str:
    """A human protein is its UniProt accession: one chain, one entry."""
    return accession


def viral_protein_id(taxon_id: int, name: str) -> str:
    """A viral protein is its curated virus and its curated name — `10407:HBx`.

    Neither the accession nor the coordinates take part: the same mature
    protein carried by several strains, or by pp1a and pp1ab alike, is one
    protein, and where it sits on each entry is an `:ON_ENTRY` annotation.
    """
    return f"{taxon_id}:{name}"


def interaction_id(id_a: str, id_b: str) -> str:
    """Join two protein ids already in slot order. See `Description.partners`."""
    return f"{id_a}|{id_b}"
