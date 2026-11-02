# Methods: the IntAct keep flag

[`methods.tsv`](methods.tsv) flags every PSI-MI detection method `yes` or `no`: does an IntAct row with this detection method enter the graph? It is the ground truth for detection methods, and `bpgraph.methods` reads it. Our curated descriptions are kept whatever their method, and methods are not grouped or counted as evidence.

## Where it comes from

The graph is for an agent that explores it to formulate biological hypotheses, such as mechanistic explanations. An IntAct row enters it when it reports **a real interaction, observed by an experiment, in a publication**, and the flag is the method's part of that judgement.

Each flag is a curator biologist's decision against that goal, from PSI-MI's definition of the term and from how IntAct uses it.

## What is `no`

- **Not an experiment**: interaction prediction and everything below it (text mining, docking, interologs, coexpression …), inference by author or curator (socio-affinity scoring and quantitative co-purification included), and `unspecified method`. These are conclusions drawn from data, not observations.
- **A family term that mixes kinds of evidence**: `biochemical`, `imaging technique`, `luminiscence technology`, `detection by mass spectrometry`, `probe interaction assay`, `labelling assay`. A row coded with one of them doesn't say whether it showed binding, a complex, or a shared place. The other family terms stay `yes`, because an experiment stands behind them.
- **Can't show two proteins physically together**:
  - light microscopy (`light`, `fluorescence`, `confocal`, `super-resolution`), FRAP and x-ray tomography, which resolve a shared place, not binding;
  - chromatin and RNA capture (ChIP and its variants, chromatin segment proteomics, RNA immunoprecipitation, DamID, chromosome conformation capture, the CLIP family), which show two proteins on the same DNA or RNA;
  - protein–nucleic acid assays (one hybrid, RNA three hybrid, DAP-seq, SELEX, southwestern blotting, the DNA footprints and interference assays);
  - `liposome binding assay`, which shows two proteins on one membrane;
  - genetic and functional assays (genetic and post-transcriptional interference, phenotype-based detection, nuclear translocation), which show an effect, not contact.

## Changing it

The flags are curation: change a row only as a decision. A detection method with no row fails the IntAct fetch, so a term PSI-MI adds must get a row; `bpgraph-methods` checks the file against a run's PSI-MI. After a change, refetch IntAct and rebuild.
