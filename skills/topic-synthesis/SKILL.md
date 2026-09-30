---
name: topic-synthesis
description: Synthesise several viral family × topic reports on one topic — written with the topic-family-report skill — into a single cross-family report that extracts the notable findings, compares the families and draws conclusions none of the reports could reach alone. Use when asked to summarise, compare or synthesise the family reports of a topic.
---

# Topic synthesis across viral families

Several reports have been written on one topic, one per viral family, each in isolation with the `topic-family-report` skill. You read them together and write one synthesis: what the families share, where they diverge, and what only appears when they are side by side.

This is a summary, not a concatenation. Report what stands out in the comparison, and leave each family's detail and figures in its report, pointing to it. A reader should get through the synthesis in about ten minutes.

## Inputs

- **Topic**, e.g. `ferroptosis`.
- **The reports**: the files or directory the user points to. Read only those. If a family's report seems to be missing or you are unsure which files are in scope, ask.
- **Destination:** wherever the user asks. Ask if they haven't said.

## Considerations

**Using the reports**

- Take the reports' numbers as they are. Don't recompute them.
- Before you build on a claim that stands out, especially one the synthesis relies on or one that conflicts with another report, check that claim against the graph. Don't re-audit the reports.
- Each report made its own judgment calls, such as the evidence tiers it included or how it handled mixed values like `both`. Mention a difference only when it affects a comparison you draw.
- Carry each finding forward with its tier and citations. Repeating it in the synthesis doesn't make it stronger.

**Comparing families**

- **Shared targets.** A topic protein hit by several unrelated families is the strongest signal a synthesis can produce: convergent evolution on a node the process depends on. Weigh it against how well studied the protein is.
- **Opposite strategies.** Families with opposite net effects on the process, or opposite consequences on the same target, need explaining. Look for a biological reason, such as the replication site, the cell type, acute versus persistent infection, or the genome type.
- **Study bias.** Many targets in a well-studied family don't mean a stronger engagement with the topic, and an absence in a sparsely studied family isn't necessarily real.
- **Hypotheses.** Merge the hypotheses that several reports reach independently, which makes them stronger, and name the reports behind each one. For hypotheses that contradict each other, set out the evidence on both sides.

**Going beyond the reports**

You may query the graph and the web to extend a cross-family pattern, for example HH links between the targets of different families, or a review that covers several of them. Keep these new findings apart from what the reports say. Label the graph, literature and hypothesis levels, and cite sources, as the reports do.

## Report structure

1. **Summary.** A few sentences: how the families engage the topic as a whole, the main convergence and the main divergence.
2. **Scope.** The topic, the reports included, and any difference in how they were built that affects the comparison.
3. **Families at a glance.** One compact table from the reports' comparison hooks, with one row per family: topic proteins targeted, net effect, key finding.
4. **Convergence.** Topic proteins and pathways targeted by several families, with the viral proteins and consequences, and what the convergence suggests.
5. **Divergence.** Where families act differently or oppositely on the topic, and the explanations the evidence supports.
6. **Cross-family hypotheses.** Specific, testable hypotheses that rest on the comparison.
7. **Disagreements and gaps.** Reports that contradict each other, claims that didn't hold against the graph, and families or topic proteins covered too sparsely to judge.
8. **Limitations.** Study bias between families, differences in how the reports were built, small counts.
