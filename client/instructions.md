# Consulting bpgraph

This repository consults bpgraph, a knowledge graph of protein–protein interactions, human–human and virus–human, through the tools of the `bpgraph` MCP server. The server says how to query the graph. This file holds the rules every query here follows, and the skills the analyses that recur.

## Evidence

The default is the **golden dataset**: interactions backed by at least 2 distinct publications or at least 2 distinct detection methods, `min_publications: 2, min_methods: 2, combine: "or"`. Interactions below it form the **all** tier, used only when asked for or when a skill says so, and always kept apart from golden counts. Say which level a result stands at.

The graph's answers come from the graph alone: when it lacks something, say so rather than filling the gap from memory.

## Two kinds of work

**Deterministic work** has one right output for a given input: drawing a network, extracting a table, checking a claim, counting. Do it directly, in one agent, so the same input gives the same result.

**Exploration** has no single right output: a hypothesis to test or to find, a mechanism to explain, an open question. Explore with subagents, as below, whether a skill is driving the work or not. When a task holds both, the exploring fans out and the rest stays with you.

## Exploring with subagents

One agent following several leads through a large graph loses track of them, so keep the leads apart.

1. **Split.** State the question and split it into leads that can be explored independently: one hypothesis, one virus or viral protein, one group of targets, one mechanism. Stay out of the graph's detail yourself.
2. **Brief.** Give each subagent its lead, its scope as ids already resolved, the evidence level and the return shape below. Launch a wave of three to six in parallel. Run leads on a fast model such as Sonnet where you can choose, and keep the strongest model for the leads the conclusion hinges on.
3. **Keep them independent.** A subagent never sees another's findings: independent runs that agree make a finding stronger.
4. **Verify.** Check the key claims of a finding yourself before your conclusion rests on it, and reconcile findings that conflict.
5. **Go again** on the leads worth deepening, with sharper briefs. Stop when a wave changes nothing.
6. **Argue both sides** of a lead the conclusion hinges on: one subagent for it, one against.

Fan out only for at least two independent leads.

**The return shape**, under about 300 words:

- **Answer**: a few sentences, with a confidence (high, medium, low) and why.
- **Claims**: each with what it rests on (interaction ids with their counters, pmids, GO ids) and whether it is the graph's, the literature's or a hypothesis.
- **Leads**: what is worth exploring next, and why.
- **Dead ends**: what was looked at and found nothing.
