"""Checking what a caller names, by the keys it knows proteins by: a UniProt
accession for a human protein, a virus's NCBI taxon id and a name for a viral
one. An unknown key is an error naming the closest known ones, never an empty
answer that reads as an absence."""

from collections.abc import Iterable
from difflib import get_close_matches

from pydantic import BaseModel, ConfigDict, Field

from bpgraph.api.base import Backend


class ViralKey(BaseModel):
    """A viral protein, as a caller names it."""

    model_config = ConfigDict(frozen=True)

    ncbi_taxon_id: int = Field(description="Its virus's NCBI taxon id, e.g. 10407.")
    name: str = Field(description="Its name within the virus, e.g. `HBx`.")


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


def check_accessions(backend: Backend, accessions: list[str]) -> None:
    """Human accessions. A gene symbol given for one is answered with it."""
    found = {
        str(row["id"])
        for row in backend.rows(
            "MATCH (p:Human) WHERE p.accession IN $ids RETURN p.accession AS id",
            ids=accessions,
        )
    }
    if missing := [a for a in dict.fromkeys(accessions) if a not in found]:
        named = {
            str(row["name"]): str(row["id"])
            for row in backend.rows(
                "MATCH (p:Human) WHERE p.name IN $names "
                "RETURN p.name AS name, p.accession AS id",
                names=missing,
            )
        }
        raise _unknown(
            "human accessions",
            {a: f"a gene symbol, of {named[a]}" if a in named else "" for a in missing},
        )


def check_viral(backend: Backend, keys: list[ViralKey]) -> None:
    """Viral proteins, each by its virus's NCBI taxon id and its name."""
    known: dict[int, set[str]] = {}
    for row in backend.rows(
        "MATCH (v:Viral) WHERE v.ncbi_taxon_id IN $taxa "
        "RETURN v.ncbi_taxon_id AS taxon, v.name AS name",
        taxa=sorted({k.ncbi_taxon_id for k in keys}),
    ):
        known.setdefault(int(str(row["taxon"])), set()).add(str(row["name"]))
    missing = [
        k for k in dict.fromkeys(keys) if k.name not in known.get(k.ncbi_taxon_id, ())
    ]
    if missing:
        notes: dict[str, str] = {}
        for k in missing:
            label = f"{k.ncbi_taxon_id} {k.name}"
            if k.ncbi_taxon_id not in known:
                notes[label] = "no curated virus has this taxon id"
            else:
                close = _closest(k.name, known[k.ncbi_taxon_id])
                notes[label] = f"closest: {', '.join(close)}" if close else ""
        raise _unknown("viral proteins", notes)


def resolve_stable_ids(
    backend: Backend, stable_ids: list[str]
) -> dict[str, tuple[int, str]]:
    """Stable ids of VH descriptions: the taxon id and name of each one's
    viral protein."""
    found = {
        str(row["id"]): row
        for row in backend.rows(
            """MATCH (d:Curated) WHERE d.stable_id IN $ids
            MATCH (d)-[:SUPPORTS]->(i:Interaction)
            OPTIONAL MATCH (i)-[:INVOLVES]->(v:Viral)
            RETURN d.stable_id AS id, v.ncbi_taxon_id AS taxon, v.name AS name""",
            ids=stable_ids,
        )
    }
    if missing := [i for i in dict.fromkeys(stable_ids) if i not in found]:
        raise _unknown("stable ids", dict.fromkeys(missing, ""))
    if wrong := [i for i in dict.fromkeys(stable_ids) if found[i]["taxon"] is None]:
        raise ValueError(
            f"not descriptions of VH interactions: {', '.join(f'`{i}`' for i in wrong)}"
        )
    return {
        i: (int(str(found[i]["taxon"])), str(found[i]["name"]))
        for i in dict.fromkeys(stable_ids)
    }
