"""Checking what a caller names: an unknown family, virus, protein, GO term,
publication, interaction or peptide is an error naming the closest known
ones, never an empty answer that reads as an absence."""

from collections.abc import Iterable
from difflib import get_close_matches

from bpgraph.api.base import KIND, Backend, ProteinKind


def _closest(name: str, known: Iterable[str]) -> list[str]:
    """Up to three known names close to `name`, whatever their case."""
    by_lower: dict[str, str] = {}
    for candidate in known:
        by_lower.setdefault(candidate.lower(), candidate)
    return [
        by_lower[match]
        for match in get_close_matches(name.lower(), by_lower, n=3, cutoff=0.6)
    ]


def _unknown(what: str, missing: dict[str, str]) -> ValueError:
    """`missing` maps each unknown name to what to say about it, if anything."""
    named = "; ".join(
        f"`{name}` ({note})" if note else f"`{name}`" for name, note in missing.items()
    )
    return ValueError(f"unknown {what}: {named}")


def _check_one(backend: Backend, what: str, name: str, label: str) -> None:
    known = [
        str(row["name"])
        for row in backend.rows(f"MATCH (n:{label}) RETURN n.name AS name")
    ]
    if name not in known:
        close = _closest(name, known)
        raise _unknown(what, {name: f"closest: {', '.join(close)}" if close else ""})


def check_scope(
    backend: Backend,
    family: str | None,
    virus: str | None,
    viral_ids: list[str] | None,
) -> None:
    """The family, the virus and the viral proteins a viral scope names."""
    if family is not None:
        _check_one(backend, "family", family, "Family")
    if virus is not None:
        _check_one(backend, "virus", virus, "Virus")
    if viral_ids is not None:
        check_proteins(backend, viral_ids, "viral")


def check_proteins(
    backend: Backend, ids: list[str], kind: ProteinKind | None = None
) -> None:
    """Protein ids, of one kind when `kind` is given. A name given for an id
    is answered with the ids it names."""
    found = {
        str(row["id"]): str(row["kind"])
        for row in backend.rows(
            f"""MATCH (p:Protein) WHERE p.id IN $ids
            RETURN p.id AS id, {KIND.format("p")} AS kind""",
            ids=ids,
        )
    }
    missing = [i for i in dict.fromkeys(ids) if i not in found]
    if missing:
        named: dict[str, list[str]] = {}
        for row in backend.rows(
            "MATCH (p:Protein) WHERE p.name IN $names "
            "RETURN p.name AS name, p.id AS id",
            names=missing,
        ):
            named.setdefault(str(row["name"]), []).append(str(row["id"]))
        viral = (
            [
                str(row["id"])
                for row in backend.rows("MATCH (v:Viral) RETURN v.id AS id")
            ]
            if any(":" in i and i not in named for i in missing)
            else []
        )
        notes: dict[str, str] = {}
        for i in missing:
            if i in named:
                notes[i] = f"a name, of {', '.join(sorted(named[i]))}"
            elif ":" in i and (close := _closest(i, viral)):
                notes[i] = f"closest: {', '.join(close)}"
            else:
                notes[i] = ""
        raise _unknown("protein ids", notes)
    if kind is not None and (
        wrong := [i for i in dict.fromkeys(ids) if found[i] != kind]
    ):
        raise ValueError(f"not {kind} proteins: {', '.join(f'`{i}`' for i in wrong)}")


def check_go_ids(backend: Backend, go_ids: list[str]) -> None:
    found = {
        str(row["go_id"])
        for row in backend.rows(
            "MATCH (g:GoTerm) WHERE g.go_id IN $ids RETURN g.go_id AS go_id",
            ids=go_ids,
        )
    }
    if missing := [i for i in dict.fromkeys(go_ids) if i not in found]:
        raise _unknown(
            "GO ids (the graph holds the terms of function annotations and "
            "every term above them)",
            dict.fromkeys(missing, ""),
        )


def check_pmids(backend: Backend, pmids: list[str]) -> None:
    found = {
        str(row["pmid"])
        for row in backend.rows(
            "MATCH (b:Publication) WHERE b.pmid IN $pmids RETURN b.pmid AS pmid",
            pmids=pmids,
        )
    }
    if missing := [p for p in dict.fromkeys(pmids) if p not in found]:
        raise _unknown(
            "pmids (the graph holds the publications backing an interaction, "
            "a GO annotation or a function text)",
            dict.fromkeys(missing, ""),
        )


def check_interactions(backend: Backend, interaction_ids: list[str]) -> None:
    """Interaction ids. One with its sides swapped is answered with the id."""
    swapped = {
        i: "|".join(reversed(i.split("|", 1))) for i in dict.fromkeys(interaction_ids)
    }
    found = {
        str(row["id"])
        for row in backend.rows(
            "MATCH (i:Interaction) WHERE i.id IN $ids RETURN i.id AS id",
            ids=[*swapped, *swapped.values()],
        )
    }
    if missing := [i for i in swapped if i not in found]:
        raise _unknown(
            "interaction ids",
            {
                i: f"it is `{swapped[i]}`" if swapped[i] in found else ""
                for i in missing
            },
        )


def check_peptide(backend: Backend, sequence: str) -> None:
    if not backend.rows(
        "MATCH (x:Peptide {sequence: $sequence}) RETURN x.sequence AS sequence",
        sequence=sequence,
    ):
        raise _unknown("peptide", {sequence: ""})
