---
name: topic-family-report
description: Analyse how one viral family acts on a topic — a curated list of human proteins such as ferroptosis — from the bpgraph protein–protein interaction graph, and write a standardized report comparable across families. Use when asked to report on or analyse one viral family's interactions with a topic's proteins; comparing several families is the topic-synthesis skill.
---

# Viral family × topic report

You analyse how one viral family acts on a topic and write a report. Each topic gets one report per family, and the `topic-synthesis` skill compares them later. So every report follows the same structure, plus whatever its family calls for.

This is an analysis, not a data dump. Explore widely, weigh the evidence, then report only what carries the argument. A reader should get through the report in about ten minutes.

## Write in isolation

Do not read or look for other reports, for any family, even ones sitting in the destination directory. Knowing what they found would bias which leads you follow and how you frame your findings, and each result would then depend on the order the reports were written. Build every judgment from the graph, the literature and the web.

## Inputs

- **Topic**, e.g. `ferroptosis`.
- **Viral family**, e.g. `Flaviviridae`.
- **Evidence threshold.** The default is the **golden dataset**: an interaction backed by at least 2 distinct publications **or** at least 2 distinct detection methods.
- **Destination:** wherever the user asks. Ask if they haven't said.

Query the live graph with `uv run bpgraph-query`, as `docs/queries.md` describes, and nothing else. The schema is in `docs/schema.md`.

## The information available

Draw on all of it. A report that uses only the interaction list is incomplete.

- **The topic.** Its human proteins, and the properties the topic records on each protein's link to it. For ferroptosis this is `role`: `driver`, `suppressor` or `both`. Other topics record other properties. Use them, whatever they are.
- **VH interactions** between the family's viral proteins and human proteins, with counters for distinct publications, methods, descriptions and peptides.
- **Descriptions.** Each one is a single observation: one pair, one publication, one detection method, and sometimes peptides with their direction.
- **Publications**, with title, abstract, journal, year and authors. Abstracts are the main source for *what* an interaction does.
- **Methods**, as PSI-MI detection methods.
- **HH interactions** among the topic's proteins and around the targets.
- **UniProt** protein names and function text, for human and viral proteins alike.
- **GO annotations**, on human proteins only, with the full ancestor closure and evidence codes.
- **NCBI taxonomy**, which rolls viral species up to their family.
- **The web**, to fill gaps: mechanisms an abstract leaves out, later papers, reviews, the family's biology.

## Considerations

Each of these is a decision to make for this family, not a fixed rule. State what you decided and why.

**Evidence**

- Apply the threshold per interaction, meaning one viral protein with one human protein. Never sum evidence across species or viral proteins to push a pair over the bar.
- Evidence below the threshold can matter. For example, a small family may have nothing golden, or a single-evidence interaction may complete a pattern the golden ones suggest. Include it if it helps, in its own clearly marked tier, and never mix it into the golden counts.
- Two methods from a single high-throughput screen are weaker than two independent studies. Look at the publications and methods behind the counts.
- The same human target hit by several species of the family suggests the interaction is conserved and functional. The same target hit by several unrelated viral proteins suggests convergence.

**Bias and background**

- Well-studied families (HIV, HCV, SARS-CoV-2, herpesviruses) have far more interactions largely because they have been studied more. Before reading much into coverage, compare it with the family's whole interactome: does the family hit topic proteins more often than its overall targeting predicts?
- For enrichment on a topic property, the natural background is the topic's own list: are suppressors over-represented among the targets compared with the whole topic? Choose each background deliberately, and name it.
- Counts are often small. Report the raw counts next to every statistic. Use an exact test (Fisher or hypergeometric) where one is meaningful, and correct for multiple testing when you test many terms. A clear qualitative pattern stated with its counts beats a weak p-value.
- Mixed values, like ferroptosis's `both`: decide whether they form their own category, get left out of a driver-versus-suppressor comparison, or get resolved per protein from the literature.

**Graph structure**

- A viral protein here is a mature chain. Several can share one polyprotein accession, so count and name viral proteins by their mature-protein name.
- Viral proteins carry no GO annotations. Their function comes from UniProt text and the literature.
- GO: drop annotations whose qualifier is `NOT`, and weigh `IEA` (electronic, unreviewed) below reviewed evidence. `regulation of X` does not sit under `X` in the ontology. Search for it by name when it matters.
- Species with no family in the taxonomy fall out of the family rollup. If a known member of the family is missing, check for that and mention it.
- In HH, a homodimer is an interaction with itself. Exclude it when listing partners.

**Network context**

- Are the targets hubs of the topic's HH subnetwork, or at its edges? Do they cluster in one module?
- Indirect reach can matter as much as direct targets: a viral protein binding an HH partner of a topic protein, such as a regulator, an E3 ligase or a transporter partner. One hop is usually enough. Go further only when a concrete hypothesis calls for it.
- Targets that are **not** in the topic's list, but that GO, UniProt function or the literature ties to the topic, are candidate additions to it. Flag them as such.

**Interpretation**

- Label three levels: what the graph says, what the literature says (the graph's abstracts plus the web), and your own hypotheses. Cite PMIDs for graph publications, and URLs or DOIs for web sources.
- A physical interaction says nothing about direction. Look to the abstracts and the web for the functional consequence, such as degradation, sequestration, relocalization, activation or inhibition, and say when it is unknown.
- Weigh the topic property against the consequence. For example, a virus that degrades a suppressor promotes the topic's process, and one that stabilizes it holds the process back. Build the family's net effect from these, including the conflicting evidence.
- Original hypotheses are the point of the report. Make them specific and testable, and tie each one to its evidence.

## Report structure

Every report has these sections, in this order. A section can be one line when it has nothing notable. Add family-specific sections after section 7, or subsections anywhere. Use tables only where they carry a comparison. If a full listing is still useful, such as every target with its evidence, put it in an appendix after section 9.

1. **Summary.** A few sentences: how the family engages the topic, its likely net effect, and the strongest finding.
2. **Scope and evidence basis.** The graph version or date if known, the family and the species present, the threshold, the tiers included, the backgrounds chosen, and any gap in the data (missing species, sparse literature).
3. **Coverage.** A table of the topic proteins targeted, with the viral protein, species, topic property and evidence (publications, methods) for each one. Then a reading of it: convergence, conservation across species, notable absences.
4. **Enrichment.** By the topic's properties (e.g. role), then by function (GO, UniProt function). Give the results that matter, each with its counts, background and test, and group the non-significant ones in a single line.
5. **Network context.** The targets' place in the topic's HH subnetwork, indirect reach, and candidate topic proteins.
6. **Mechanisms.** One entry per interaction, or group of interactions, that decides the net effect or supports a hypothesis: what the viral protein does to its target, and what that means for the topic. Name the remaining targets in one line.
7. **Net effect and hypotheses.** The family's overall action on the topic, with the conflicting evidence and your confidence, then the hypotheses.
8. **Limitations.** Study bias, small counts, missing directionality, what the graph does not cover.
9. **Comparison hooks.** A short, fixed-format block that the synthesis reads:
   - topic proteins targeted (golden / all tiers), out of the topic total
   - targeted proteins broken down by the topic property
   - viral proteins involved
   - net effect on the topic, in one word or phrase (e.g. *pro-ferroptotic*, *anti-ferroptotic*, *mixed*, *undetermined*)
   - top three findings, one line each
