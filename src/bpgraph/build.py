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


def _viral_keys(prepared: Prepared) -> dict[str, Row]:
    """Each viral protein's key, by its reference in the build's files. One
    entry per curated viral protein: a fixed list, small beside the data."""
    return {
        p.ref: {"ncbi_taxon_id": int(p.virus_id), "name": p.name}
        for p in _viral(prepared)
    }


def _key(ref: str, viral: dict[str, Row]) -> tuple[ProteinKind, Row]:
    """The kind and key of the protein a reference names."""
    if ref in viral:
        return ProteinKind.VIRAL, viral[ref]
    return ProteinKind.HUMAN, {"accession": ref}


def _human_proteins(prepared: Prepared) -> Iterator[Row]:
    for _, row in rows(prepared.host.swissprot):
        yield {
            "accession": row["accession"],
            "name": row["name"],
            "description": row["description"],
            "function": row["function"],
        }


def _viral_proteins(prepared: Prepared) -> Iterator[Row]:
    """Every distinct function text a protein's members carry, as paragraphs."""
    for protein in _viral(prepared):
        yield {
            "ncbi_taxon_id": int(protein.virus_id),
            "name": protein.name,
            "function": "\n\n".join(protein.function.split(SEPARATOR)),
        }


def _human_citations(prepared: Prepared) -> Iterator[Row]:
    for cursor, row in rows(prepared.host.swissprot):
        for pmid in listed(cursor, row, "pmids"):
            yield {"accession": row["accession"], "pmid": pmid}


def _viral_citations(prepared: Prepared) -> Iterator[Row]:
    for protein in _viral(prepared):
        for pmid in filter(None, protein.pmids.split(";")):
            yield {
                "ncbi_taxon_id": int(protein.virus_id),
                "name": protein.name,
                "pmid": pmid,
            }


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


def _interactions(
    writer: GraphWriter, prepared: Prepared, viral: dict[str, Row]
) -> dict[str, int]:
    """Each interaction with its descriptions, read together with its
    peptides from the two files sorted by interaction. The counters are
    counted here, from the group, and the interaction is written with them
    and its descriptions."""
    counts = {"interactions": 0, "descriptions": 0}
    groups = files.cogroup(
        files.read(prepared.descriptions), files.read(prepared.reports), 1
    )
    for chunk in batched(groups, BATCH_SIZE, strict=False):
        claims: dict[InteractionKind, list[Row]] = {k: [] for k in InteractionKind}
        for _, found, peptides in chunk:
            members = [of(Description, record) for record in found]
            first = members[0]
            kind = InteractionKind(first.kind)
            side_b = (
                {"b": first.side_b}
                if kind is InteractionKind.HH
                else {
                    "b_taxon_id": viral[first.side_b]["ncbi_taxon_id"],
                    "b_name": viral[first.side_b]["name"],
                }
            )
            claims[kind].append(
                {
                    "a": first.side_a,
                    **side_b,
                    "n_descriptions": len(members),
                    "n_publications": len({d.pmid for d in members}),
                    "n_methods": len({d.method_id for d in members}),
                    "n_peptides": len({of(Report, r).sequence for r in peptides}),
                    "descriptions": [
                        {
                            "pmid": d.pmid,
                            "method_id": d.method_id,
                            "method_name": d.method_name,
                            "stable_id": d.stable_id,
                        }
                        for d in members
                    ],
                }
            )
            counts["descriptions"] += len(members)
        for kind, rows_of_kind in claims.items():
            counts["interactions"] += interactions.write_interactions(
                writer, kind, rows_of_kind
            )
    return counts


def _reports(prepared: Prepared) -> Iterator[Report]:
    return (of(Report, r) for r in files.read(prepared.reports))


def _peptide_proteins(
    writer: GraphWriter, prepared: Prepared, viral: dict[str, Row]
) -> dict[str, int]:
    """Each peptide's descriptions, the proteins it was cut from and the ones
    it binds."""
    counts = {
        "reports": interactions.write_reports(
            writer,
            (
                {"stable_id": r.stable_id, "sequence": r.sequence}
                for r in _reports(prepared)
            ),
        )
    }
    for relation, field in (("FROM", "source"), ("BINDS", "target")):
        for kind in ProteinKind:
            counts[f"peptide_{relation.lower()}_{kind.name.lower()}"] = (
                interactions.write_peptide_proteins(
                    writer,
                    relation,
                    kind,
                    (
                        {"sequence": r.sequence, **key}
                        for r in _reports(prepared)
                        for found, key in [_key(getattr(r, field), viral)]
                        if found is kind
                    ),
                )
            )
    return counts


def _go_terms(prepared: Prepared) -> Iterator[Row]:
    """The terms annotated, and their ancestors. GO detaches a term it retires
    from the hierarchy, so a term here marked obsolete is an annotation to a
    retired term, and fails the build."""
    for cursor, row in rows(prepared.host.go_terms):
        if row["obsolete"] == "True":
            raise cursor.fail(f"{row['go_id']} is obsolete and annotated")
        yield {
            "go_id": row["go_id"],
            "name": row["name"],
            "namespace": row["namespace"],
        }


def _go_annotations(prepared: Prepared, scratch: Path) -> Iterator[Row]:
    """One annotation per protein, term and qualifier, with each publication
    showing it and the evidence codes its GOA lines give."""
    lines = files.sorted_file(
        scratch / "go_annotations",
        (
            [
                row["accession"],
                row["go_id"],
                row["qualifier"],
                row["pmid"],
                row["evidence_code"],
            ]
            for _, row in rows(prepared.host.go_annotations)
        ),
        unique=True,
    )
    for (accession, go_id, qualifier), found in files.groups(files.read(lines), 3):
        codes: dict[str, list[str]] = {}
        for record in found:
            codes.setdefault(record[3], []).append(record[4])
        yield {
            "accession": accession,
            "go_id": go_id,
            "qualifier": qualifier,
            "publications": [
                {"pmid": pmid, "evidence_codes": evidence}
                for pmid, evidence in codes.items()
            ],
        }


def _load(writer: GraphWriter, prepared: Prepared, scratch: Path) -> dict[str, int]:
    """Every write of a run, in dependency order: a relationship is created
    once both its endpoints exist."""
    host = prepared.host
    families = {family.taxon_id: family for _, family in prepared.families}
    viral = _viral_keys(prepared)
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
                {"ncbi_taxon_id": v.taxon_id, "name": v.name, "full_name": v.full_name}
                for v in prepared.viruses
            ),
        ),
        "families": taxonomy.write_families(
            writer,
            ({"ncbi_taxon_id": f.taxon_id, "name": f.name} for f in families.values()),
        ),
        "taxon_links": taxonomy.write_taxon_links(
            writer,
            (
                {"child_taxon_id": virus, "parent_taxon_id": family.taxon_id}
                for virus, family in prepared.families
            ),
        ),
        "memberships": taxonomy.write_memberships(writer, viral.values()),
        "publications": interactions.write_publications(
            writer, _publications(prepared)
        ),
        "function_cites": proteins.write_function_citations(
            writer, ProteinKind.HUMAN, _human_citations(prepared)
        )
        + proteins.write_function_citations(
            writer, ProteinKind.VIRAL, _viral_citations(prepared)
        ),
        "peptides": interactions.write_peptides(writer, _peptides(prepared, scratch)),
    }
    counts |= _interactions(writer, prepared, viral)
    counts |= _peptide_proteins(writer, prepared, viral)
    counts["go_terms"] = annotations.write_go_terms(writer, _go_terms(prepared))
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
        writer, _go_annotations(prepared, scratch)
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
                (
                    int(s.virus_id),
                    s.name,
                    s.accession,
                    int(s.start),
                    int(s.stop),
                    s.sequence,
                )
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
