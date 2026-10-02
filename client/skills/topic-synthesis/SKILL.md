---
name: topic-synthesis
description: Synthesise several viral family × topic reports on one topic — written with the topic-family-report skill — into a single cross-family report that extracts the notable findings, compares the families and draws conclusions none of the reports could reach alone. Use when asked to summarise, compare or synthesise the family reports of a topic. Writing one family's report is the topic-family-report skill; drawing a subnetwork is the network-view skill.
---

# Topic synthesis across viral families

Several reports have been written on one topic, one per viral family, each in isolation with the `topic-family-report` skill. You read them together and write one synthesis: what the families share, where they diverge, and what only appears when they are side by side.

This is a summary, not a concatenation. Report what stands out in the comparison, and leave each family's detail and figures in its report, pointing to it. A reader should get through the synthesis in about ten minutes.

## Inputs

- **Topic**, e.g. `ferroptosis`: a list of human proteins in a file or knowledge base on your side, which the user points to; ask where it is if they haven't said. Read its Swiss-Prot accessions and whatever it records on each protein, such as a `role`. Pass the accessions to tools as `accessions`, and join the list's other columns to the results yourself; `find_proteins` turns gene symbols into accessions. The list decides every count, so name the file and its date in what you write.
- **The reports**: the files or directory the user points to. Read only those. If a family's report seems to be missing, or you are unsure which files are in scope, ask.
- **Evidence level**: golden by default. When you check a report's claim, check it at the level the report made it.
- **Destination**: wherever the user asks; ask if they haven't said. Name the synthesis `<topic>-synthesis.md`, e.g. `ferroptosis-synthesis.md`.

## Tools

The tools this synthesis leans on:

| for                                       | tools                                           |
| ----------------------------------------- | ----------------------------------------------- |
| checking a report's claim                 | `vh_interactions`, `evidence`, `publications`   |
| the families side by side on the topic    | `coverage`, `cypher`                            |
| how well studied a protein is             | `proteins` (its human and viral partner counts) |
| links between different families' targets | `hh_interactions`, `cypher`                     |

## Considerations

**Using the reports**

- Take the reports' numbers as they are. Don't recompute them.
- Check that the reports were built from the same topic file, at the same date, as the one you were given. A report built from another version of the list is not comparable as it stands: say so.
- Before you build on a claim that stands out, especially one the synthesis relies on or one that conflicts with another report, check it against the graph. Don't re-audit the reports.
- Each report made its own judgment calls, such as the tiers it included or how it handled mixed values like `both`. Mention a difference only when it affects a comparison you draw.
- Carry each finding forward with its tier and citations. Repeating it in the synthesis doesn't make it stronger.

**Comparing families**

- **Shared targets.** A topic protein hit by several unrelated families is the strongest signal a synthesis can produce: convergent evolution on a node the process depends on. Count the families reaching each topic protein, each through interactions at the evidence level, with `cypher`, and weigh the count against how well studied the protein is:

  ```cypher
  MATCH (h:Protein) WHERE h.id IN $accessions AND h:Human
  WITH h
  MATCH (h)-[e:INTERACTS_WITH]-(v:Viral)
  WITH h, e, v
  WHERE e.n_publications >= 2 OR e.n_methods >= 2
  MATCH (v)-[:IN_TAXON]->(:Virus)-[:PARENT]->(f:Family)
  RETURN h.name AS protein, count(DISTINCT f) AS n_families,
         collect(DISTINCT f.name) AS families
  ORDER BY n_families DESC, protein
  ```

- **Opposite strategies.** Families with opposite net effects on the process, or opposite consequences on the same target, need explaining. Look for a biological reason, such as the replication site, the cell type, acute versus persistent infection, or the genome type.

- **Study bias.** Many targets in a well-studied family don't mean a stronger engagement with the topic, and an absence in a sparsely studied family isn't necessarily real.

- **Hypotheses.** Merge the hypotheses that several reports reach independently, which makes them stronger, and name the reports behind each one. For hypotheses that contradict each other, set out the evidence on both sides.

**Going beyond the reports**

- You may query the graph and the web to extend a cross-family pattern, for example HH links between the targets of different families, or a review that covers several of them. Keep these new findings apart from what the reports say.
- **Three levels.** Label what the graph says, what the literature says (the graph's abstracts plus the web), and your own hypotheses. Cite PMIDs for graph publications, and URLs or DOIs for web sources.

## The synthesis

Every synthesis has these sections, in this order. A section can be one line when it has nothing notable.

1. **Summary.** A few sentences: how the families engage the topic as a whole, the main convergence and the main divergence.
2. **Scope.** The topic file and its date, the reports included, the date the graph was queried for any check, and any difference in how the reports were built that affects the comparison.
3. **Families at a glance.** One compact table built from the reports' comparison hooks, one row per family: topic proteins targeted (golden / all tiers), net effect, top finding.
4. **Convergence.** Topic proteins and pathways targeted by several families, with the viral proteins and consequences, and what the convergence suggests.
5. **Divergence.** Where families act differently or oppositely on the topic, and the explanations the evidence supports.
6. **Cross-family hypotheses.** Specific, testable hypotheses that rest on the comparison.
7. **Disagreements and gaps.** Reports that contradict each other, claims that didn't hold against the graph, and families or topic proteins covered too sparsely to judge.
8. **Limitations.** Study bias between families, differences in how the reports were built, small counts.

## Report back

Give the path of the synthesis, the reports it covers, the main convergence and the main divergence in one line each, and any report claim that did not hold against the graph.
