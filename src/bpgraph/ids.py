"""The only place a bpgraph identifier is constructed.

Some labels need a derived id because their natural key is several values at
once; every other label keys on a value that comes straight from the data. See
docs/schema.md section 3.
"""


def human_protein_id(accession: str) -> str:
    """A host protein is its UniProt accession: one chain, one entry."""
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


def intact_description_id(intact_id: str, accession_a: str, accession_b: str) -> str:
    """An IntAct observation of one pair. IntAct spoke-expands a complex into
    one row per pair under a single interaction id, so the id alone is not
    enough. The accessions are in slot order."""
    return f"{intact_id}|{accession_a}|{accession_b}"


def annotation_id(
    protein_id: str,
    go_id: str,
    pmid: str,
    evidence_code: str,
    assigned_by: str,
    qualifier: str,
) -> str:
    """Everything an annotation is. The qualifier comes last because it may
    hold a `|` of its own — `NOT|enables`."""
    return f"{protein_id}|{go_id}|{pmid}|{evidence_code}|{assigned_by}|{qualifier}"
