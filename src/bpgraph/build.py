"""Running a build: prepare, write into staging, validate, swap, publish vaults.

The live graph is never written to. A run builds beside it and publishes with a
single `RENAME`, so a bad export cannot land on something people are querying.

Every step streams: the preparation reads the run a line at a time into files
in the run's `build/`, and the graph is written from those files in batches.
Nothing whole is ever held in memory, and `build/` is removed when the build
ends, whether it succeeded or not. docs/build.md tells the whole order.
"""

import logging
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import batched
from pathlib import Path

from falkordb import FalkorDB

from bpgraph import files, schema, vault
from bpgraph.client import BATCH_SIZE, GraphWriter, Row
from bpgraph.config import Config
from bpgraph.enums import GoRelation, InteractionKind, ProteinKind
from bpgraph.ids import annotation_id, human_protein_id
from bpgraph.loaders.records import (
    SEPARATOR,
    Description,
    Report,
    Site,
    ViralProtein,
    of,
)
from bpgraph.loaders.run import Prepared, prepare
from bpgraph.loaders.tsv import listed, rows
from bpgraph.pubmed import AUTHOR_SEPARATOR
from bpgraph.run import Run
from bpgraph.schema import ConstraintRow
from bpgraph.write import annotations, interactions, proteins, taxonomy

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BuildReport:
    """What a run wrote, and the constraint states it passed."""

    graph: str
    counts: dict[str, int]
    constraints: list[ConstraintRow]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _reset(db: FalkorDB, name: str) -> None:
    # The key, not GRAPH.LIST, which once missed a graph that was there.
    if db.connection.exists(name):
        db.select_graph(name).delete()


def _viral(prepared: Prepared) -> Iterator[ViralProtein]:
    return (of(ViralProtein, r) for r in files.read(prepared.viral_proteins))


def _human_proteins(prepared: Prepared) -> Iterator[Row]:
    for _, row in rows(prepared.host.swissprot):
        yield {
            "id": human_protein_id(row["accession"]),
            "name": row["name"],
            "description": row["description"],
            "function": row["function"],
        }


def _viral_proteins(prepared: Prepared) -> Iterator[Row]:
    """Every distinct text a protein's members carry: names on one line,
    function texts as paragraphs."""
    for protein in _viral(prepared):
        yield {
            "id": protein.id,
            "name": protein.name,
            "description": "; ".join(protein.description.split(SEPARATOR)),
            "function": "\n\n".join(protein.function.split(SEPARATOR)),
        }


def _citations(prepared: Prepared) -> Iterator[Row]:
    for cursor, row in rows(prepared.host.swissprot):
        protein = human_protein_id(row["accession"])
        for pmid in listed(cursor, row, "pmids"):
            yield {"protein_id": protein, "pmid": pmid}
    for protein in _viral(prepared):
        for pmid in filter(None, protein.pmids.split(";")):
            yield {"protein_id": protein.id, "pmid": pmid}


def _publications(prepared: Prepared) -> Iterator[Row]:
    for pmid, title, year, journal, authors, abstract in files.read(
        prepared.publications
    ):
        yield {
            "pmid": pmid,
            "title": title,
            "year": int(year),
            "journal": journal,
            "abstract": abstract,
            "authors": [a for a in authors.split(AUTHOR_SEPARATOR) if a],
        }


def _peptides(prepared: Prepared, scratch: Path) -> Iterator[Row]:
    sequences = files.sorted_file(
        scratch / "peptides",
        ([of(Report, r).sequence] for r in files.read(prepared.reports)),
        unique=True,
    )
    for (sequence,) in files.read(sequences):
        yield {"sequence": sequence, "length": len(sequence)}


def _interactions(writer: GraphWriter, prepared: Prepared) -> dict[str, int]:
    """Each interaction with its descriptions and their peptides, read
    together from the two files sorted by interaction. The counters are
    counted here, from the group, and the interaction is written with them."""
    counts = {"interactions": 0, "descriptions": 0, "reported_peptides": 0}
    curated_only = 0
    groups = files.cogroup(
        files.read(prepared.descriptions), files.read(prepared.reports), 1
    )
    for chunk in batched(groups, BATCH_SIZE, strict=False):
        claims: dict[InteractionKind, list[Row]] = {k: [] for k in InteractionKind}
        observations: list[Row] = []
        reported: list[Row] = []
        for (identity,), found, peptides in chunk:
            members = [of(Description, record) for record in found]
            first = members[0]
            kind = InteractionKind(first.kind)
            if kind is InteractionKind.HH and not any(d.intact_id for d in members):
                curated_only += 1
            claims[kind].append(
                {
                    "id": identity,
                    "side_a": first.side_a,
                    "side_b": first.side_b,
                    "n_descriptions": len(members),
                    "n_publications": len({d.pmid for d in members}),
                    "n_peptides": len({of(Report, r).sequence for r in peptides}),
                }
            )
            observations.extend(
                {
                    "id": d.id,
                    "intact_id": d.intact_id,
                    "stable_ids": [s for s in d.stable_ids.split(";") if s],
                    "interaction_id": identity,
                    "pmid": d.pmid,
                    "method_id": d.method_id,
                    "method_name": d.method_name,
                }
                for d in members
            )
            reported.extend(
                {
                    "description_id": p.description_id,
                    "sequence": p.sequence,
                    "source_side": p.source_side,
                }
                for p in (of(Report, r) for r in peptides)
            )
        for kind, rows_of_kind in claims.items():
            counts["interactions"] += interactions.write_interactions(
                writer, kind, rows_of_kind
            )
        counts["descriptions"] += interactions.write_descriptions(writer, observations)
        counts["reported_peptides"] += interactions.write_reported_peptides(
            writer, reported
        )
    logger.info("HH: %d interactions only our curation reports", curated_only)
    return counts


def _go_annotations(prepared: Prepared) -> Iterator[Row]:
    for _, row in rows(prepared.host.go_annotations):
        protein = human_protein_id(row["accession"])
        yield {
            "id": annotation_id(
                protein,
                row["go_id"],
                row["pmid"],
                row["evidence_code"],
                row["assigned_by"],
                row["qualifier"],
            ),
            "protein_id": protein,
            "go_id": row["go_id"],
            "pmid": row["pmid"],
            "qualifier": row["qualifier"],
            "evidence_code": row["evidence_code"],
            "assigned_by": row["assigned_by"],
        }


def _load(writer: GraphWriter, prepared: Prepared, scratch: Path) -> dict[str, int]:
    """Every write of a run, in dependency order: a relationship is created
    once both its endpoints exist."""
    host = prepared.host
    families = {family.taxon_id: family for _, family in prepared.families}
    counts = {
        "human_proteins": proteins.write_proteins(
            writer, ProteinKind.HUMAN, _human_proteins(prepared)
        ),
        "viral_proteins": proteins.write_proteins(
            writer, ProteinKind.VIRAL, _viral_proteins(prepared)
        ),
        "viruses": taxonomy.write_viruses(
            writer,
            (
                {"taxon_id": v.taxon_id, "name": v.name, "full_name": v.full_name}
                for v in prepared.viruses
            ),
        ),
        "families": taxonomy.write_families(
            writer,
            ({"taxon_id": f.taxon_id, "name": f.name} for f in families.values()),
        ),
        "taxon_links": taxonomy.write_taxon_links(
            writer,
            (
                {"child_taxon_id": virus, "parent_taxon_id": family.taxon_id}
                for virus, family in prepared.families
            ),
        ),
        "memberships": taxonomy.write_memberships(
            writer,
            (
                {"protein_id": p.id, "taxon_id": int(p.virus_id)}
                for p in _viral(prepared)
            ),
        ),
        "publications": interactions.write_publications(
            writer, _publications(prepared)
        ),
        "function_cites": proteins.write_function_citations(
            writer, _citations(prepared)
        ),
        "peptides": interactions.write_peptides(writer, _peptides(prepared, scratch)),
    }
    counts |= _interactions(writer, prepared)
    counts["go_terms"] = annotations.write_go_terms(
        writer,
        (
            {
                "go_id": row["go_id"],
                "name": row["name"],
                "namespace": row["namespace"],
                "obsolete": row["obsolete"] == "True",
            }
            for _, row in rows(host.go_terms)
        ),
    )
    counts["go_edges"] = sum(
        annotations.write_go_edges(
            writer,
            relation,
            (
                {"child_go_id": row["child_go_id"], "parent_go_id": row["parent_go_id"]}
                for _, row in rows(host.go_edges)
                if row["relation"] == relation.value
            ),
        )
        for relation in GoRelation
    )
    counts["go_annotations"] = annotations.write_go_annotations(
        writer, _go_annotations(prepared)
    )
    return counts


def build(
    db: FalkorDB, prepared: Prepared, config: Config, scratch: Path
) -> BuildReport:
    """Write a prepared run into staging and publish it.

    Raises `ConstraintsNotSatisfied` if the run violates a key, leaving the
    live graph untouched and dropping the staging graph.
    """
    _reset(db, config.staging_graph)
    staging = db.select_graph(config.staging_graph)

    # Indexes before the data so every MATCH during the load is index-backed;
    # constraints after it, so a duplicate shows up as a FAILED constraint.
    schema.create_indexes(staging)
    try:
        counts = _load(GraphWriter(staging), prepared, scratch)
        schema.create_constraints(staging)
        constraints = schema.validate_constraints(staging)
    except BaseException:
        _reset(db, config.staging_graph)
        raise

    db.connection.rename(config.staging_graph, config.live_graph)
    return BuildReport(graph=config.live_graph, counts=counts, constraints=constraints)


def write_vaults(run: Run, prepared: Prepared) -> list[Path]:
    """The host's sequences, and the viral entries, mature proteins and
    observations."""
    host = prepared.host
    sites = (of(Site, r) for r in files.read(prepared.sites))
    return [
        vault.write_host(
            run.vault,
            host.vault,
            ((row["accession"], row["sequence"]) for _, row in rows(host.sequences)),
        ),
        vault.write_viral(
            run.vault,
            run.viral.vault,
            ((a, int(t), n, d) for a, t, n, d in files.read(prepared.entries)),
            (
                (s.protein_id, s.accession, int(s.start), int(s.stop), s.sequence)
                for s in sites
            ),
            ((d, a) for d, a in files.read(files.sort(prepared.observations))),
        ),
    ]


def main() -> None:
    """Build one run directory into the live graph and its vaults, and report
    what went in.

    `uv run bpgraph-build data/2026-09-09` prepares every silo of the run into
    `build/`, builds the graph through staging, writes the vaults and publishes
    them beside the live graph, removes `build/`, and prints the counts and the
    release of every public dataset the run was fetched from.
    """
    import sys

    from bpgraph.client import connect
    from bpgraph.sources import read_sources

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-build <run directory>")
    run = Run(Path(sys.argv[1]))
    config = Config.from_env()
    scratch = run.build
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir()
    try:
        logger.info("preparing %s", run.directory)
        prepared = prepare(run, scratch)
        logger.info("writing %s", config.staging_graph)
        report = build(connect(config), prepared, config, scratch)
        written = vault.publish(write_vaults(run, prepared), config.vault)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    for name, count in report.counts.items():
        print(f"{name:<18} {count:>9,}")
    print(f"{'total':<18} {report.total:>9,}  -> {report.graph}")
    for path in written:
        print(f"vault {path}")
    for source in read_sources(run.sources):
        print(
            f"{source.dataset:<12} {source.release:<32} {source.fetched}  {source.url}"
        )
