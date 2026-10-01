"""The graph's shape as data, restated by hand from docs/schema.md: its labels
and their properties, the labels that carry a type, and its relationships.

The audit checks the live graph against it, and the query API's `schema`
describes the graph from it, so what consumers read is what the audit holds.
"""

from collections.abc import Mapping

NODE_PROPERTIES: Mapping[str, Mapping[str, str]] = {
    "Protein": {
        "id": "String",
        "name": "String",
        "description": "String",
        "function": "String",
    },
    "Virus": {"taxon_id": "Integer", "name": "String", "full_name": "String"},
    "Family": {"taxon_id": "Integer", "name": "String"},
    "Publication": {
        "pmid": "String",
        "title": "String",
        "abstract": "String",
        "journal": "String",
        "year": "Integer",
        "authors": "List",
    },
    "Interaction": {
        "id": "String",
        "n_descriptions": "Integer",
        "n_publications": "Integer",
        "n_methods": "Integer",
        "n_peptides": "Integer",
    },
    "Description": {
        "id": "String",
        "intact_id": "String",
        "stable_ids": "List",
        "method_id": "String",
        "method_name": "String",
    },
    "Annotation": {
        "id": "String",
        "qualifier": "String",
        "evidence_code": "String",
        "assigned_by": "String",
    },
    "Peptide": {"sequence": "String", "length": "Integer"},
    "GoTerm": {
        "go_id": "String",
        "name": "String",
        "namespace": "String",
        "obsolete": "Boolean",
    },
}
"""Every property schema.md lists, and the type FalkorDB should report for it.

A missing property types as `Null`, so one test catches both absence and drift.
`:Taxon` is checked through its two sublabels, whose properties differ.
"""

SUBLABELS: Mapping[str, tuple[str, str]] = {
    "Protein": ("Human", "Viral"),
    "Interaction": ("HH", "VH"),
    "Taxon": ("Virus", "Family"),
}
"""Labels that carry a type: exactly one of the pair, beside the base label."""

RELATIONSHIPS: tuple[tuple[str, str, str, tuple[str, ...] | None], ...] = (
    ("INVOLVES", "Interaction", "Protein", ("side",)),
    ("FUNCTION_CITES", "Protein", "Publication", ()),
    ("SUPPORTS", "Description", "Interaction", ()),
    ("REPORTED_IN", "Description|Annotation", "Publication", ()),
    ("REPORTS", "Description", "Peptide", ("source_side",)),
    ("IN_TAXON", "Viral", "Virus", ()),
    ("PARENT", "Virus", "Family", ()),
    (
        "INTERACTS_WITH",
        "Protein",
        "Protein",
        (
            "interaction_id",
            "n_descriptions",
            "n_publications",
            "n_methods",
            "n_peptides",
        ),
    ),
    ("ANNOTATES", "Annotation", "Human", ()),
    ("OF_TERM", "Annotation", "GoTerm", ()),
    ("IS_A", "GoTerm", "GoTerm", ()),
    ("PART_OF", "GoTerm", "GoTerm", ()),
)
"""Type, the labels it must join — `|` separating the labels a source may
carry — and its properties. `None` means they vary."""
