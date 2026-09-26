"""Putting a run's silos together into one snapshot, and its vaults.

Each silo loads on its own: the host from what was fetched for it, the viral
silo from our VH rows and what was fetched for them. What they share is joined
here, and nowhere else:

- **Methods.** Every PSI-MI term any silo uses must have a curated class, or
  the load fails naming the terms, as an uncurated viral taxon does. A method
  is named from PSI-MI, not from whatever copy of the name a source carries.
- **Publications.** A pmid two silos cite is one node. Only pmids something
  cites become nodes, and a cited pmid with no metadata in any silo fails the
  load: run `bpgraph-pubmed`.
- **GO.** The terms every annotation reaches, and their ancestor closure.
- **Topics**, curated lists of host proteins.
- **Peptides**, which the export attaches to a curated row: each silo places
  those of its own rows.
"""

import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from bpgraph.enums import InteractionKind
from bpgraph.go import read_ontology as read_go
from bpgraph.loaders.export import export_rows, peptide_references
from bpgraph.loaders.host import HostSilo, load_host
from bpgraph.loaders.tsv import LoadError, make, required, rows
from bpgraph.loaders.viral import ViralSilo, load_viral
from bpgraph.methods import ROOT, MethodClasses
from bpgraph.models import (
    Description,
    Involvement,
    Method,
    Protein,
    ProteinRef,
    Publication,
    Snapshot,
    Topic,
)
from bpgraph.psimi import read_ontology as read_psimi
from bpgraph.pubmed import read_publications
from bpgraph.run import HUMAN, Run
from bpgraph.taxonomy import Taxonomy
from bpgraph.vault import HostVault, ViralVault
from bpgraph.viruses import CuratedViruses

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Loaded:
    """What a run builds: the graph, and a vault per silo."""

    snapshot: Snapshot
    hosts: tuple[HostVault, ...]
    viral: ViralVault


def _methods(
    descriptions: tuple[Description, ...],
    classes: Mapping[str, str],
    names: Mapping[str, str],
) -> tuple[Method, ...]:
    used = sorted({d.psimi_id for d in descriptions})
    return tuple(
        Method(psimi_id=p, name=names[p], method_class=classes[p]) for p in used
    )


def _publications(run: Run, cited: set[str]) -> tuple[Publication, ...]:
    """The cited pmids, from whichever silo fetched each first."""
    found: dict[str, Publication] = {}
    for path in (run.host(HUMAN).publications, run.viral.publications):
        for pmid, article in read_publications(path).items():
            if pmid in cited and pmid not in found:
                found[pmid] = Publication(
                    pmid=article.pmid,
                    title=article.title,
                    year=article.year,
                    journal=article.journal,
                    abstract=article.abstract,
                    authors=article.authors,
                )
    missing = cited - set(found)
    if missing:
        raise LoadError(
            f"{len(missing)} cited pmids have no metadata, e.g. "
            f"{', '.join(sorted(missing)[:5])}: run bpgraph-pubmed {run.directory}"
        )
    return tuple(found[pmid] for pmid in sorted(found, key=int))


def _involvements(run: Run, hosts: Mapping[str, Protein]) -> Iterator[Involvement]:
    """Every topic list in the run's `topics/`, one topic per file.

    A list may name an accession that is not a host protein — retired from
    Swiss-Prot since it was resolved — so it is logged and left out rather than
    failing the run.
    """
    for path in sorted(run.topics.glob("*.tsv")):
        absent: list[str] = []
        for cursor, row in rows(path):
            accession = required(cursor, row, "accession")
            protein = hosts.get(accession)
            if protein is None:
                absent.append(accession)
                continue
            yield make(
                cursor,
                Involvement,
                protein=ProteinRef(id=protein.id, kind=protein.kind),
                topic=path.stem,
                properties={k: v for k, v in row.items() if k != "accession"},
            )
        if absent:
            logger.warning(
                "%s: %d accessions are not host proteins: %s",
                path.name,
                len(absent),
                ", ".join(absent),
            )


@dataclass(frozen=True, slots=True)
class RunLoader:
    """Reads one run directory. See docs/build.md for what it holds."""

    run: Run
    taxonomy: Taxonomy
    viruses: CuratedViruses

    @classmethod
    def open(cls, directory: Path) -> Self:
        """Read `directory` against the taxonomy fetched into it and the
        curated virus list."""
        run = Run(directory)
        taxonomy = Taxonomy.open(run.taxonomy)
        return cls(run, taxonomy, CuratedViruses.load(taxonomy))

    def load(self) -> Loaded:
        run = self.run
        psimi = read_psimi(run.psimi)
        curated = list(export_rows(run.export, psimi))
        references = peptide_references(run.export)
        host_paths = run.host(HUMAN)
        classes = MethodClasses.load(psimi).resolve(
            (
                {row.psimi_id for row in curated}
                | {required(c, r, "psimi_id") for c, r in rows(host_paths.intact)}
            )
            - {ROOT}
        )

        host: HostSilo = load_host(
            host_paths,
            [row for row in curated if row.kind is InteractionKind.HH],
            references,
            classes,
        )
        viral: ViralSilo = load_viral(
            run.viral,
            [row for row in curated if row.kind is InteractionKind.VH],
            references,
            host.proteins,
            self.taxonomy,
            self.viruses,
        )
        orphans = set(references) - host.stable_ids - viral.stable_ids
        if orphans:
            raise LoadError(
                f"peptides.tsv names {len(orphans)} descriptions absent from "
                f"descriptions.tsv, e.g. {', '.join(sorted(orphans)[:5])}"
            )

        descriptions = (*host.descriptions, *viral.descriptions)
        citations = (*host.citations, *viral.citations)
        cited = (
            {d.pmid for d in descriptions}
            | {a.pmid for a in host.annotations}
            | {c.pmid for c in citations}
        )
        go = read_go(run.ontology)
        go_terms, go_edges = go.closure({a.go_id for a in host.annotations})
        viruses = viral.viruses
        families, taxon_links = self.taxonomy.families(v.taxon_id for v in viruses)
        involvements = tuple(_involvements(run, host.proteins))
        names = {term: psimi.terms[term].name for term in classes}

        snapshot = Snapshot(
            proteins=(*host.proteins.values(), *viral.proteins.values()),
            function_citations=citations,
            viruses=viruses,
            families=families,
            taxon_links=taxon_links,
            memberships=viral.memberships,
            topics=tuple(
                Topic(name=name) for name in sorted({i.topic for i in involvements})
            ),
            involvements=involvements,
            publications=_publications(run, cited),
            methods=_methods(descriptions, classes, names),
            descriptions=descriptions,
            go_terms=tuple(go_terms),
            go_edges=tuple(go_edges),
            go_annotations=host.annotations,
        )
        return Loaded(snapshot=snapshot, hosts=(host.vault,), viral=viral.vault)
