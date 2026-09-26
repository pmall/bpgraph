# Method classes — why they are what they are

[`methods.tsv`](methods.tsv) groups PSI-MI detection methods into classes. `Interaction.n_methods` counts classes, so the one question behind every row is: **would an interaction seen by both methods count as confirmed by two independent techniques?** If not, they share a class. When in doubt, merge: the golden dataset is better off undercounting independent evidence than overcounting it.

A term takes the class of the most specific row enclosing it in PSI-MI. A term under two rows that disagree needs a row of its own, and `uv run bpgraph-methods <run directory>` fails naming it, as it fails on a term no row encloses. Run it after every change: it prints each class with its terms and how many export and IntAct rows use them.

## The calls

- **Two hybrid** is every transcriptional complementation assay (`MI:0232`): yeast two hybrid and all its array, pooling and validated variants, bacterial and three hybrid. PSI-MI splits them by screening design, not by technique.
- **Membrane two hybrid** (`MI:2412`, split-ubiquitin) is its own class, although PSI-MI puts it under two hybrid: a different reporter, used where two hybrid cannot reach membrane proteins.
- **Protein complementation assay** is every other split-reporter reconstitution: BiFC, split luciferase, MAPPIT, DHFR, β-lactamase and the rest. It stays apart from two hybrid, since the two are the standard orthogonal pair of virus–host screens. The export codes the Gaussia luciferase PCA as `MI:0090` or as the `gaussia luciferase protein tag`; both land here.
- **Affinity purification** is capturing a bait from cells and reading what came with it: co-IP of every kind, tandem affinity purification, LUMIER, and the generic `affinity chromatography technology` and `affinity technology`. Co-IP and TAP are one class: both purify the bait's complex from a lysate, and a co-IP confirming an AP-MS hit confirms the identification, not the association.
  - **Chromatin immunoprecipitation array** (`MI:0225`) sits under both affinity chromatography and array technology. It captures with an antibody, so it is affinity purification.
  - **Mass spectrometry terms are affinity purification.** The export codes AP-MS screens as `mass spectrometry studies of complexes` (`MI:0069`, 59k rows: Shah 2018, Ewing 2007 …), and as `silac` or identification-by-MS terms. The detection method behind them is the purification.
- **Pull down** is capture by a recombinant bait, mostly in vitro, so evidence of a different kind from co-IP. `holdup assay` joins it.
- **Binding assay** is binding between purified partners on a solid phase or in solution: ELISA, far western, filter binding, bead aggregation, competition and saturation binding.
- **Protein array** covers protein, peptide and antibody arrays alike, `surface plasmon resonance array` included.
- **Cofractionation** is co-migration by size, density or charge: size exclusion, ion exchange, gradients, native and SDS gels, mobility shift.
- **Proximity labelling** (BioID and kin), **proximity ligation assay**, **cross-linking**, **display technology**, **footprinting** and **aggregation assay** are each one technique.
- **Enzymatic assay** is every enzymatic study, and the export's interaction types that name a reaction (`phosphorylation reaction` …), which record the assay that showed it.
- **Biophysics** is split by technique, because each is an independent physical readout: **biosensor** (SPR, BLI), **calorimetry**, **crystallography**, **nuclear magnetic resonance**, **electron microscopy**, **scattering**, **spectroscopy** (CD, IR, UV-vis, EPR), **energy transfer** (FRET, BRET, HTRF, AlphaScreen) and **fluorescence** (polarization, FCS, FACS). The long tail — thermophoresis, thermal shift, HDX-MS — is **biophysical**.
- **Imaging** is light and atomic force microscopy.
- **Unspecified** is what says nothing about the technique: the generic `experimental interaction detection` and `biochemical`, and the export's terms from outside the detection branch — feature detection, tags, attributes, `direct interaction`.

## Dropped

A description coded `MI:0000 molecular interaction`, the root of PSI-MI, is dropped: the export uses it as a placeholder on one row, and it says nothing about the method. A row for it would enclose every term and turn the gate off.
