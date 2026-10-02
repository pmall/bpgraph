"""The graph's shape as data, restated by hand from docs/schema.md: its labels
and their properties, the labels that carry a type, and its relationships.

The audit checks the live graph against it.
"""

from collections.abc import Mapping

NODE_PROPERTIES: Mapping[str, Mapping[str, str]] = {
    "Human": {
        "accession": "String",
        "name": "String",
        "description": "String",
        "function": "String",
    },
    "Viral": {"ncbi_taxon_id": "Integer", "name": "String", "function": "String"},
    "Virus": {"ncbi_taxon_id": "Integer", "name": "String", "full_name": "String"},
    "Family": {"ncbi_taxon_id": "Integer", "name": "String"},
    "Publication": {
        "pmid": "String",
        "title": "String",
        "abstract": "String",
        "journal": "String",
        "year": "Integer",
        "authors": "List",
    },
    "Interaction": {
        "n_descriptions": "Integer",
        "n_publications": "Integer",
        "n_methods": "Integer",
        "n_peptides": "Integer",
    },
    "Curated": {"stable_id": "String", "method_id": "String", "method_name": "String"},
    "IntAct": {"method_id": "String", "method_name": "String"},
    "Annotation": {"qualifier": "String"},
    "Peptide": {"sequence": "String", "length": "Integer"},
    "GoTerm": {"go_id": "String", "name": "String", "namespace": "String"},
}
"""Every property schema.md lists, and the type FalkorDB should report for it.

A missing property types as `Null`, so one test catches both absence and drift.
A label with sublabels whose properties differ is checked through them.
"""

SUBLABELS: Mapping[str, tuple[str, str]] = {
    "Protein": ("Human", "Viral"),
    "Interaction": ("HH", "VH"),
    "Taxon": ("Virus", "Family"),
    "Description": ("Curated", "IntAct"),
}
"""Labels that carry a type: exactly one of the pair, beside the base label."""

RELATIONSHIPS: tuple[tuple[str, str, str, tuple[str, ...] | None], ...] = (
    ("INVOLVES", "Interaction", "Protein", ()),
    ("FUNCTION_CITES", "Protein", "Publication", ()),
    ("SUPPORTS", "Description", "Interaction", ()),
    ("REPORTED_IN", "Description|Annotation", "Publication", None),
    ("REPORTS", "Curated", "Peptide", ()),
    ("FROM", "Peptide", "Protein", ()),
    ("BINDS", "Peptide", "Protein", ()),
    ("IN_TAXON", "Viral", "Virus", ()),
    ("PARENT", "Virus", "Family", ()),
    (
        "INTERACTS_WITH",
        "Protein",
        "Protein",
        ("n_descriptions", "n_publications", "n_methods", "n_peptides"),
    ),
    ("ANNOTATES", "Annotation", "Human", ()),
    ("OF_TERM", "Annotation", "GoTerm", ()),
    ("IS_A", "GoTerm", "GoTerm", ()),
    ("PART_OF", "GoTerm", "GoTerm", ()),
)
"""Type, the labels it must join — `|` separating the labels a source may
carry — and its properties. `None` means they vary: `REPORTED_IN` from an
annotation carries `evidence_codes`, from a description nothing."""
