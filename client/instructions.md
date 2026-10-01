# Consulting bpgraph

This repository consults bpgraph, a knowledge graph of protein–protein interactions, human–human and virus–human, through the tools of the `bpgraph` MCP server. The graph's interactions are backed by publications, titles and abstracts included, and its human proteins carry their UniProt function text and experimental GO annotations. It is built to produce hypotheses: its counters say where the evidence is, and its text says what the evidence means.

The server's instructions and the tool descriptions explain how to read the graph: which tool answers which question and what the data means. The `schema` tool gives its structure and the rules for writing Cypher. The skills hold the analyses that recur.

## Two kinds of work

**Deterministic work** has one right output for a given input: drawing a network, extracting a table, checking a claim against the graph, counting. Do it directly, in one agent, so the same input gives the same result.

**Exploration** has no single right output: a hypothesis to test or to find, a mechanism to explain, the analysis inside a family report, a synthesis, any open question. Two runs may rightly take different paths and reach different findings. Explore with subagents, as below, whether a skill is driving the work or not.

When a task holds both, as a report does, the exploring fans out and the rest, such as assembling the report, stays with you.

## Exploring with subagents

A single agent following several leads through a large graph loses track of them: each lead's queries and abstracts crowd out the others. Keep the leads apart instead.

1. **Frame and split.** State the question, then split it into leads that can be explored independently: one hypothesis, one virus or viral protein, one group of targets, one mechanism, one angle on the evidence. Stay out of the graph's detail yourself; your context is for the question as a whole.
2. **Brief each lead.** Give each subagent its lead, its scope and the return shape below. Pass the scope as ids already resolved, accessions and viral protein ids, with the evidence level, so the subagent starts from them instead of looking names up again. Launch the leads of a wave in parallel; three to six is a good size. A lead is one bounded task ending in a compact finding, which a fast model such as Sonnet does well: run leads on one wherever you can choose a subagent's model, and keep the strongest model for the leads the conclusion hinges on, and for yourself.
3. **Keep them independent.** A subagent sees its brief, the graph and the web, never another subagent's findings. Independent runs that agree make a finding stronger; that only holds if they did not see each other.
4. **Verify what you build on.** Before a finding carries your conclusion, check its key claims yourself with `evidence` and `publications`. Reconcile findings that conflict.
5. **Go again where it pays.** Launch a second wave on the leads worth deepening, with briefs sharpened by the first. Stop when a wave adds nothing that changes the conclusion.
6. **Use the disagreement.** For a lead the conclusion hinges on, brief two subagents with opposite tasks, one building the case for it and one against. Their agreement or disagreement is itself a finding.

A subagent costs a fresh start, so fan out when there are at least two independent leads, and give each brief what the subagent needs and no more.

**The return shape.** Each subagent returns a compact finding, not a transcript:

- **Answer**: the lead's answer in a few sentences, with a confidence (high, medium, low) and why.
- **Claims**: each with what it rests on: interaction ids with their counters, pmids, GO ids, and the level it stands at — what the graph says, what the literature says, or a hypothesis.
- **Leads**: what is worth exploring next, and why.
- **Dead ends**: what was looked at and found nothing, so no wave looks again.

## Spending tokens well

- **Counts before rows.** `limit: 1` returns a count: the first line of a table gives the total.
- **Titles before abstracts.** Call `publications` with `abstracts: true` only for the papers that matter.
- **Lean Cypher.** Return aggregates, and only the columns the question needs.
- **Short returns.** A lead's return stays under about 300 words.

## Recipes

- **A family on a topic.** `coverage` places the family among the others, against its overall reach. `vh_interactions` with the family and the topic's accessions gives the interactions, `evidence` the observations behind the ones that matter, and `publications` their abstracts. `hh_interactions` with `around` and `neighbours` show the human context; `indirect_reach` adds the targets reached through one protein in between.
- **What a family's targets do.** Take the human proteins of `vh_interactions` for the family, and pass them to `go_rollup` with a reference set as `background`, such as the topic or every human protein the family's virus reaches: each term comes with the counts an exact test needs.
- **From a word to the graph.** `search_publications` finds the papers, `publication_content` what each backs: interactions, GO annotations, function texts.
- **Drafting a topic.** `search_go_terms` finds the terms, `go_term_proteins` the proteins under them, `neighbours` the candidates the list misses. The draft goes to the user, who curates it into the topic's file.

## What you write

- **Three levels.** Label what the graph says, what the literature says (the graph's abstracts plus the web), and your own hypotheses. Cite PMIDs for graph publications, and URLs or DOIs for web sources.
- **Evidence.** Give the evidence level a result stands at, and the counts behind every claim. The default is the golden dataset: interactions backed by at least 2 distinct publications or at least 2 distinct detection methods.
- **Where it came from.** Name the date the graph was queried, and any file a result depends on, such as a topic's list.
