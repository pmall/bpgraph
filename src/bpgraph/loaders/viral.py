"""The viral silo: our virus–host interactions, probing a host interactome.

A viral protein is a curated mature protein of a curated virus, whichever
strains and accessions it was observed on: its id is its virus and its name,
so every strain's copy of `HBx` lands on one protein. Its sites — each entry
and span it was observed at — come from our kept VH rows, their sequences from
`viral_proteins.tsv`.

Its members are one chain by definition, so they should carry one function
text and one UniProt name. That is checked rather than assumed: a protein
keeps every distinct text its members carry, and the ones carrying more than
one are listed for curation to look at, as are names within one virus that
differ only in case, and members whose lengths differ by more than half.

Where each viral protein sits on each entry and its residues there, the
entry's strain, and which entry each description used go to the viral vault
rather than the graph.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.ids import interaction_id
from bpgraph.loaders.records import (
    KEPT,
    SEPARATOR,
    Curated,
    Description,
    Site,
    ViralProtein,
    of,
)
from bpgraph.loaders.tsv import LoadError, integer, listed, required, rows, text
from bpgraph.run import ViralPaths

logger = logging.getLogger(__name__)

LENGTH_SPREAD = 0.5
"""A viral protein whose shortest member is under half its longest is
reported: those members may not be one chain."""

FUNCTION, NAME = "f", "n"


@dataclass(frozen=True, slots=True)
class ViralFiles:
    proteins: Path
    """`ViralProtein` records."""
    entries: Path
    """The vault's entries: accession, strain id, strain name, UniProt name."""


def vh_descriptions(
    curated: Path, name_of: Callable[[str], str], out: TextIO, observations: TextIO
) -> None:
    """Write the kept VH rows as descriptions, and which entry each observed."""
    for record in files.read(curated):
        row = of(Curated, record)
        if row.kind != InteractionKind.VH.value or row.status != KEPT:
            continue
        description = Description(
            interaction_id=interaction_id(row.accession_1, row.partner_2),
            id=row.stable_id,
            intact_id="",
            stable_ids=row.stable_id,
            kind=InteractionKind.VH.value,
            side_a=row.accession_1,
            side_b=row.partner_2,
            pmid=row.pmid,
            method_id=row.psimi_id,
            method_name=name_of(row.psimi_id),
            method_class=row.method_class,
        )
        out.write("\t".join(description) + "\n")
        observations.write(f"{row.stable_id}\t{row.accession_2}\n")


def _texts(
    viral: ViralPaths, by_site: Path, exported: Path, scratch: Path
) -> Iterator[list[str]]:
    """`[protein_id, f, text, pmids, site]` for each function text of each
    site. A text for a span the export does not have means the file no longer
    matches it."""
    functions = files.sorted_file(
        scratch / "functions_by_site",
        (
            [
                required(c, r, "accession"),
                str(integer(c, r, "start")),
                str(integer(c, r, "stop")),
                required(c, r, "function"),
                ";".join(listed(c, r, "pmids")),
            ]
            for c, r in rows(viral.functions)
        ),
    )
    for site, texts, known in files.cogroup(
        files.read(functions), files.read(exported), 3
    ):
        if texts and not known:
            raise LoadError(
                f"{viral.functions.name}: {':'.join(site)} is not in the export: "
                "run bpgraph-functions again"
            )
    for _, found, texts in files.cogroup(files.read(by_site), files.read(functions), 3):
        if found and texts:
            site = of(Site, found[0], 3)
            for _, _, _, function, pmids in texts:
                yield [site.protein_id, FUNCTION, function, pmids, ":".join(site[3:6])]


def _names(
    viral: ViralPaths, sites: Path, scratch: Path, entries: TextIO
) -> Iterator[list[str]]:
    """`[protein_id, n, name, '', accession]` for each site whose entry UniProt
    names; and the vault's entries written as they pass. An entry has one
    strain."""
    by_accession = files.sorted_file(
        scratch / "sites_by_accession",
        ([of(Site, r).accession, *r] for r in files.read(sites)),
    )
    names = files.sorted_file(
        scratch / "names_by_accession",
        (
            [required(c, r, "accession"), text(c, r, "description")]
            for c, r in rows(viral.entries)
        ),
    )
    for (accession,), found, named in files.cogroup(
        files.read(by_accession), files.read(names), 1
    ):
        if not found:
            continue
        members = [of(Site, record, 1) for record in found]
        strains = {(site.strain_id, site.strain_name) for site in members}
        if len(strains) > 1:
            raise LoadError(f"{accession} is of several taxa: {sorted(strains)}")
        (strain_id, strain_name), *_ = strains
        name = named[0][1] if named else ""
        entries.write(f"{accession}\t{strain_id}\t{strain_name}\t{name}\n")
        if name:
            for site in members:
                yield [site.protein_id, NAME, name, "", accession]


def _distinct(values: list[str]) -> list[str]:
    return sorted(set(values))


def _disagree(carried: list[list[str]], kind: str) -> bool:
    """Whether the members carrying a kind of text carry different ones. One
    entry may hold several texts — a generic one beside a curated one — and
    that is no disagreement; members holding different sets are."""
    held: dict[str, set[str]] = {}
    for record in carried:
        if record[1] == kind:
            held.setdefault(record[4], set()).add(record[2])
    return len({frozenset(texts) for texts in held.values()}) > 1


def viral_proteins(
    viral: ViralPaths, sites: Path, exported: Path, scratch: Path
) -> ViralFiles:
    """Assemble the viral proteins from their sites, and check that the members
    of each agree."""
    by_site = files.sorted_file(
        scratch / "sites_by_site", ([*of(Site, r)[3:6], *r] for r in files.read(sites))
    )
    entries = scratch / "vault_entries"
    texts = scratch / "texts"
    with entries.open("w", encoding="utf-8") as handle:
        files.write(texts, _texts(viral, by_site, exported, scratch))
        with texts.open("a", encoding="utf-8") as more:
            for record in _names(viral, sites, scratch, handle):
                more.write("\t".join(record) + "\n")
    files.sort(texts, unique=True)
    by_protein = files.sorted_file(scratch / "sites_by_protein", files.read(sites))

    proteins = scratch / "viral_proteins_final"
    several_functions: list[str] = []
    several_names: list[str] = []
    spread: list[str] = []
    with proteins.open("w", encoding="utf-8") as out:
        for (identity,), found, carried in files.cogroup(
            files.read(by_protein), files.read(texts), 1
        ):
            members = [of(Site, record) for record in found]
            functions = _distinct([r[2] for r in carried if r[1] == FUNCTION])
            names = _distinct([r[2] for r in carried if r[1] == NAME])
            pmids = dict.fromkeys(
                pmid
                for r in carried
                if r[1] == FUNCTION
                for pmid in r[3].split(";")
                if pmid
            )
            if _disagree(carried, FUNCTION):
                several_functions.append(identity)
            if _disagree(carried, NAME):
                several_names.append(identity)
            lengths = [int(m.stop) - int(m.start) + 1 for m in members]
            if min(lengths) < LENGTH_SPREAD * max(lengths):
                spread.append(f"{identity} {min(lengths)}-{max(lengths)}")
            protein = ViralProtein(
                id=identity,
                virus_id=members[0].virus_id,
                name=members[0].name,
                description=SEPARATOR.join(names),
                function=SEPARATOR.join(functions),
                pmids=";".join(pmids),
            )
            out.write("\t".join(protein) + "\n")

    for label, listed_ids in (
        ("have members carrying different function texts", several_functions),
        ("have members carrying different UniProt names", several_names),
        ("have members differing in length by more than half", spread),
    ):
        if listed_ids:
            logger.warning(
                "%d viral proteins %s: %s",
                len(listed_ids),
                label,
                ", ".join(listed_ids),
            )
    _case_collisions(proteins, scratch)
    return ViralFiles(proteins=proteins, entries=files.sort(entries, unique=True))


def _case_collisions(proteins: Path, scratch: Path) -> None:
    """Names within one virus that differ only in case are two proteins —
    genuinely so for EBV's `BARF1` and `BaRF1`, but any new pair is worth a
    look."""
    folded = files.sorted_file(
        scratch / "folded",
        (
            [p.virus_id, p.name.lower(), p.name]
            for p in (of(ViralProtein, r) for r in files.read(proteins))
        ),
        unique=True,
    )
    collisions = [
        f"{virus} {'/'.join(r[2] for r in found)}"
        for (virus, _), found in files.groups(files.read(folded), 2)
        if len(found) > 1
    ]
    if collisions:
        logger.warning(
            "%d viral protein names differ only in case: %s",
            len(collisions),
            "; ".join(collisions),
        )
