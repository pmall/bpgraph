# Publications: groups that repeat one experiment

[`publications.tsv`](publications.tsv) lists groups of publications that report the same experiment again: BioPlex 3.0 re-reports the BioPlex 2.0 pull-downs, MuSIC re-analyses BioPlex 3.0. IntAct curates each publication on its own and never merges them, so each would give its own description of the same observation, and a pair seen once would count two publications. The list is not exhaustive: it holds the obvious cases, large enough to matter.

## What it does

It applies to IntAct only; our curated descriptions are always kept. Within a group, a pair keeps the rows of the lowest pmid that reports it, the publication PubMed indexed first, and drops the others. So a pair reported in both BioPlex 2.0 and 3.0 keeps its 2.0 description, and a pair only 3.0 reports keeps its 3.0 one. Publications outside every group are unaffected.

## Changing it

A row is `group`, `pmid` and a `note` saying what the publication is and why it is grouped. A pmid is in one group at most, and a group has at least two publications. After a change, refetch IntAct and rebuild.
