---
name: topic-family-report
description: Analyse how one viral family acts on a topic — a curated list of human proteins such as ferroptosis, read from a file on the client side — from the bpgraph protein–protein interaction graph, and write a standardized report comparable across families. Use when asked to report on or analyse one viral family's interactions with a topic's proteins. Comparing several families' reports is the topic-synthesis skill; drawing a subnetwork is the network-view skill.
---

# Viral family × topic report

You analyse how one viral family acts on a topic, and write a report. Each topic gets one report per family, and the `topic-synthesis` skill compares them, so every report follows the same structure, plus whatever its family calls for.

This is an analysis, not a data dump. Explore widely, weigh the evidence, then report only what carries the argument. A reader should get through the report in about ten minutes.

**Write in isolation.** Do not read or look for other reports, for any family, even ones in the destination directory. Knowing what they found would bias which leads you follow and how you frame your findings, and each result would then depend on the order the reports were written. Build every judgment from the graph, the literature and the web.

## Inputs

- **Topic**, e.g. `ferroptosis`: a list of human proteins in a file or knowledge base on your side, which the user points to; ask where it is if they haven't said. Read its Swiss-Prot accessions and whatever it records on each protein, such as a `role`. Pass the accessions to your queries as a parameter, and join the list's other columns to the results yourself; a human protein's `name` in the graph is its gene symbol. The list decides every count, so name the file and its date in what you write.
- **Viral family**, e.g. `Flaviviridae`, as the graph's `:Family` names it.
- **Evidence level**: golden by default.
- **Destination**: wherever the user asks; ask if they haven't said. Name the report `<topic>-<family>.md`, e.g. `ferroptosis-flaviviridae.md`.

## The graph

**Start from the standard query.** `queries/vh-interactions.cypher`, in this skill's folder, returns the family's VH interactions with the topic's proteins: virus, viral protein, human protein and counters. Run it with `cypher` exactly as written, with `accessions`, `family` and `golden` as parameters, once with `golden: true` and once with `golden: false`. Every report starts from these rows, so reports compare across families: the coverage table and the comparison hooks count them.

Beyond it, query with `cypher`, in patterns that go as far as the question does: from the family's viruses through their viral proteins and interactions to the topic's proteins, directly or through a protein in between, and on to the descriptions, publications and GO annotations behind them.

## The information available

Draw on all of it. A report that uses only the interaction list is incomplete.

- **The topic**: its proteins, and what the list records on each. For ferroptosis this is `role`: `driver`, `suppressor` or `both`. Other topics record other properties; use them, whatever they are.
- **VH interactions** between the family's viral proteins and human proteins, with their counters.
- **Descriptions**, one per observation, each with its publication, its detection method, its source (IntAct or our curation) and sometimes peptides with their direction.
- **Publications**, with title, abstract, journal, year and authors. Abstracts are the main source for *what* an interaction does.
- **HH interactions** among the topic's proteins and around the targets.
- **UniProt** names and function text, for human and viral proteins alike.
- **GO annotations** on human proteins: experimental, biological process and molecular function only, each with its publication, and the ontology above them for rolling up.
- **Curated viruses** (`HBV`, `SARS-CoV-2`) and their NCBI family.
- **The web**, to fill gaps: mechanisms an abstract leaves out, later papers, reviews, the family's biology.

## Considerations

Each of these is a decision to make for this family, not a fixed rule. State what you decided and why.

**Evidence**

- Below the evidence level can still matter: a small family may have nothing golden, or a single-evidence interaction may complete a pattern the golden ones suggest. Include it if it helps, in the all tier, never mixed into the golden counts.
- Look at the publications and methods behind the counts, not only the counts.
- The same human target hit by several viruses of the family suggests the interaction is conserved and functional. The same target hit by several unrelated viral proteins suggests convergence.

**Bias and background**

- Well-studied families (HIV, HCV, SARS-CoV-2, herpesviruses) have far more interactions largely because they have been studied more. Before reading much into coverage, compare it with the family's whole interactome, every human protein the family reaches: does the family hit topic proteins more often than its overall reach predicts?
- For enrichment on a topic property, the natural background is the topic's own list: are suppressors over-represented among the targets compared with the whole topic? Choose each background deliberately, and name it.
- Counts are often small. Give the raw counts next to every statistic. Use an exact test (Fisher or hypergeometric) where one is meaningful, and correct for multiple testing when you test many terms. A clear qualitative pattern stated with its counts beats a weak p-value.
- Mixed values, like ferroptosis's `both`: decide whether they form their own category, are left out of a driver-versus-suppressor comparison, or are resolved per protein from the literature.

**The family in the graph**

- Count and name viral proteins by virus and name. `viral_sequences` gives a protein's strains and sequences, for verifying one protein.
- A protein none of whose UniProt entries is reviewed has no function text; one whose entries word it differently holds each text, as separate paragraphs.
- A virus with no family in the taxonomy falls out of the family. If a known member of the family is missing, check the graph's viruses and say so.
- GO: an annotation's abstract can be read like an interaction's.

**Network context**

- Are the targets central to the topic's HH subnetwork, or at its edges? Do they cluster? Answer from the graph's structure with `cypher`. For example, each topic protein's golden partners within the topic, beside its partners across the proteome, separates a protein central to the topic from a hub of everything:

  ```cypher
  MATCH (h:Human) WHERE h.accession IN $accessions
  WITH h
  MATCH (h)-[e:INTERACTS_WITH]-(n:Human)
  WITH h, e, n
  WHERE n <> h AND (e.n_publications >= 2 OR e.n_methods >= 2)
  RETURN h.name AS protein,
         count(DISTINCT CASE WHEN n.accession IN $accessions THEN n END) AS in_topic,
         count(DISTINCT n) AS in_proteome
  ORDER BY in_topic DESC, in_proteome DESC
  ```

- Indirect reach can matter as much as direct targets: a viral protein binding an HH partner of a topic protein, such as a regulator, an E3 ligase or a transporter partner. One protein in between is usually enough; go further only when a concrete hypothesis calls for it. Hubs such as ubiquitin, chaperones and the baits of large screens connect almost everything, so a path through one is weak evidence of anything.

- Targets that are **not** in the topic's list, but that GO, UniProt function or the literature ties to the topic, are candidate additions to it. Flag them as such.

**Interpretation**

- **Three levels.** Label what the graph says, what the literature says (the graph's abstracts plus the web), and your own hypotheses. Cite PMIDs for graph publications, and URLs or DOIs for web sources.
- A physical interaction says nothing about direction. Look to the abstracts and the web for the functional consequence, such as degradation, sequestration, relocalization, activation or inhibition, and say when it is unknown.
- Weigh the topic property against the consequence. For example, a virus that degrades a suppressor promotes the topic's process, and one that stabilizes it holds the process back. Build the family's net effect from these, including the conflicting evidence.
- Original hypotheses are the point of the report. Make them specific and testable, and tie each one to its evidence.

## The report

Every report has these sections, in this order. A section can be one line when it has nothing notable. Add family-specific sections after section 7, or subsections anywhere. Use tables only where they carry a comparison. If a full listing is still useful, such as every target with its evidence, put it in an appendix after section 9. A network figure, if the report needs one, is drawn with the `network-view` skill.

1. **Summary.** A few sentences: how the family engages the topic, its likely net effect, and the strongest finding.
2. **Scope and evidence basis.** The topic file and its date, the date the graph was queried, the family and the viruses present, the evidence level, the tiers included, the backgrounds chosen, and any gap in the data (missing viruses, sparse literature).
3. **Coverage.** A table of the topic proteins targeted, with the viral protein, virus, topic property and evidence (publications, methods) for each one. Then a reading of it: convergence, conservation across viruses, notable absences.
4. **Enrichment.** By the topic's properties (e.g. role), then by function (GO, UniProt function). Give the results that matter, each with its counts, background and test, and group the non-significant ones in a single line.
5. **Network context.** The targets' place in the topic's HH subnetwork, indirect reach, and candidate topic proteins.
6. **Mechanisms.** One entry per interaction, or group of interactions, that decides the net effect or supports a hypothesis: what the viral protein does to its target, and what that means for the topic. Name the remaining targets in one line.
7. **Net effect and hypotheses.** The family's overall action on the topic, with the conflicting evidence and your confidence, then the hypotheses.
8. **Limitations.** Study bias, small counts, missing directionality, what the graph does not cover.
9. **Comparison hooks.** A short, fixed-format block that `topic-synthesis` reads:
   - topic proteins targeted, golden / all tiers, out of the topic total
   - targeted proteins broken down by the topic property
   - viral proteins involved
   - net effect on the topic, in one word or phrase (e.g. *pro-ferroptotic*, *anti-ferroptotic*, *mixed*, *undetermined*)
   - top three findings, one line each

## Report back

Give the path of the report, the evidence level, the net effect, the three strongest findings in one line each, and anything you could not settle.
