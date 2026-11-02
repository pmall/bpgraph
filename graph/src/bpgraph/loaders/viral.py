"""The viral silo: our virus–host interactions, probing a host interactome.

A viral protein is the one curation groups its rows under, as
`bpgraph.loaders.export` says, so every strain's copy of `HBx` lands on one
protein. Its sites — each entry and span it was observed at — come from our
kept VH rows, their sequences from `interactors_viral`. A protein keeps every
distinct function text its members carry.

Where each viral protein sits on each entry and its residues there, the
entry's strain and the UniProt release it was recorded from, and which entry
each description used go to the viral vault rather than the graph.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.loaders.records import (
    KEPT,
    SEPARATOR,
    Curated,
    Description,
    Site,
    ViralProtein,
    of,
    pair_ref,
)
from bpgraph.loaders.tsv import LoadError, integer, listed, required, rows, text
from bpgraph.run import ViralPaths


@dataclass(frozen=True, slots=True)
class ViralFiles:
    proteins: Path
    """`ViralProtein` records."""
    entries: Path
    """The vault's entries: accession, strain id, strain name, release,
    UniProt name."""


def vh_descriptions(
    curated: Path, name_of: Callable[[str], str], out: TextIO, observations: TextIO
) -> None:
    """Write the kept VH rows as descriptions, and which entry each observed."""
    for record in files.read(curated):
        row = of(Curated, record)
        if row.kind != InteractionKind.VH.value or row.status != KEPT:
            continue
        description = Description(
            interaction=pair_ref(row.accession_1, row.partner_2),
            kind=InteractionKind.VH.value,
            side_a=row.accession_1,
            side_b=row.partner_2,
            pmid=row.pmid,
            method_id=row.psimi_id,
            method_name=name_of(row.psimi_id),
            stable_id=row.stable_id,
        )
        out.write("\t".join(description) + "\n")
        observations.write(f"{row.stable_id}\t{row.accession_2}\n")


def _texts(
    viral: ViralPaths, by_site: Path, exported: Path, scratch: Path
) -> Iterator[list[str]]:
    """`[ref, text, pmids]` for each function text of each site. A text
    for a span the export does not have means the file no longer matches it."""
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
                yield [site.ref, function, pmids]


def _entries(viral: ViralPaths, sites: Path, scratch: Path, entries: TextIO) -> None:
    """Write the vault's entries: each with its strain and release, which are
    one, and the name UniProt gives it."""
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
        recorded = {
            (site.strain_id, site.strain_name, site.release) for site in members
        }
        if len(recorded) > 1:
            raise LoadError(
                f"{accession} is of several taxa or releases: {sorted(recorded)}"
            )
        (strain_id, strain_name, release), *_ = recorded
        name = named[0][1] if named else ""
        entries.write(f"{accession}\t{strain_id}\t{strain_name}\t{release}\t{name}\n")


def viral_proteins(
    viral: ViralPaths, sites: Path, exported: Path, scratch: Path
) -> ViralFiles:
    """Assemble the viral proteins from their sites."""
    by_site = files.sorted_file(
        scratch / "sites_by_site", ([*of(Site, r)[3:6], *r] for r in files.read(sites))
    )
    entries = scratch / "vault_entries"
    with entries.open("w", encoding="utf-8") as handle:
        _entries(viral, sites, scratch, handle)
    texts = files.sorted_file(
        scratch / "texts", _texts(viral, by_site, exported, scratch), unique=True
    )
    by_protein = files.sorted_file(scratch / "sites_by_protein", files.read(sites))

    proteins = scratch / "viral_proteins_final"
    with proteins.open("w", encoding="utf-8") as out:
        for (identity,), found, carried in files.cogroup(
            files.read(by_protein), files.read(texts), 1
        ):
            members = [of(Site, record) for record in found]
            functions = sorted({r[1] for r in carried})
            pmids = dict.fromkeys(
                pmid for r in carried for pmid in r[2].split(";") if pmid
            )
            protein = ViralProtein(
                ref=identity,
                virus_id=members[0].virus_id,
                name=members[0].name,
                function=SEPARATOR.join(functions),
                pmids=";".join(pmids),
            )
            out.write("\t".join(protein) + "\n")
    return ViralFiles(proteins=proteins, entries=files.sort(entries, unique=True))
