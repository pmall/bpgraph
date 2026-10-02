---
name: network-view
description: Draw a subnetwork of the bpgraph protein–protein interaction graph as an interactive HTML page — e.g. one viral family's interactions with a topic such as ferroptosis, at a chosen evidence level. Use when asked to visualize, draw, plot or show a network, subnetwork or interactome from the graph. Analysing a family on a topic is the topic-family-report skill; comparing families is the topic-synthesis skill.
---

# Network view

You draw a subnetwork of the graph as an interactive page, in three steps:

1. **Gather the dataset.** Query the graph, choose what the network holds, and write it to `<name>.json`. This is your judgment.
2. **Render it.** Run `uv run <this skill's folder>/render.py <name>.json`. It writes a standard page, `<name>.cytoscape.html`, beside the JSON, from the `cytoscape.html` template next to the script. Every network goes through that template, so networks share one look and compare directly.
3. **Adjust the page**, if the network calls for it: colours, labels, shapes or layout, in the page's `adjust` block and nowhere else.

## Inputs

- **What to draw**, e.g. ferroptosis × Flaviviridae. Ask if it is unclear.
- **Topic**, if the network is drawn around one, e.g. `ferroptosis`: a list of human proteins in a file or knowledge base on your side, which the user points to; ask where it is if they haven't said. Read its Swiss-Prot accessions and whatever it records on each protein, such as a `role`. Pass the accessions to tools as `accessions`, and join the list's other columns to the results yourself; `find_proteins` turns gene symbols into accessions. The list decides every count, so name the file and its date in what you write.
- **Viral family**, if the network is drawn around one, e.g. `Flaviviridae`, as `viruses` names it.
- **Evidence level**: golden by default. The all tier is drawn only when asked for, and said so in the description.
- **Destination**: wherever the user asks; ask if they haven't said. Name the files after the network, `<topic>-<family>.json` for a topic × family network, e.g. `ferroptosis-flaviviridae.json`.

## Tools

The tools a network leans on, for a topic × family network:

| for                                                                | tools                                                        |
| ------------------------------------------------------------------ | ------------------------------------------------------------ |
| the VH edges, each with its viral protein, virus and counters      | `vh_interactions` with the family and the topic's accessions |
| the HH edges among the topic's proteins and the targets outside it | `hh_interactions` with those accessions                      |
| each human protein's description                                   | `proteins`                                                   |
| anything else the network should hold, such as one-hop partners    | `neighbours`, `indirect_reach`, `cypher`                     |

A network's edges are compact, so raising `max_tokens` is usually fine here.

## 1. The dataset

```json
{
  "title": "Ferroptosis × Flaviviridae (golden)",
  "description": "One or two sentences: what is drawn, and the evidence level applied.",
  "proteins": [
    {"id": "P36969", "name": "GPX4", "kind": "human",
     "description": "Phospholipid hydroperoxide glutathione peroxidase",
     "taxon_name": "Homo sapiens", "attributes": {"role": "suppressor"}},
    {"id": "3052230:NS5A", "name": "NS5A", "kind": "viral",
     "description": "Genome polyprotein", "taxon_name": "HCV"}
  ],
  "interactions": [
    {"source": "P36969", "target": "3052230:NS5A", "n_publications": 2,
     "n_methods": 3}
  ]
}
```

- `id` is the graph's protein id. `kind` is `human` or `viral`.
- `taxon_name` is the virus's name for a viral protein (`HCV`, `SARS-CoV-2`), as the tools give it, and `Homo sapiens` for a human one.
- `attributes` is optional: anything else worth showing or styling by, such as the `role` the topic's list gives a protein, or the viral family. It appears when a protein is clicked, and the page can style by it.
- An interaction connects two listed proteins, and each pair appears once. `n_publications` and `n_methods` are the interaction's counters, as the tools return them.
- The renderer refuses a file that breaks these rules.

Write the `description` for a reader who has not seen how the data was gathered. Name the topic, the family, the evidence level, and anything included beyond the direct interactions, such as HH edges, untargeted topic proteins or one-hop partners.

**Keep it readable.** A few hundred proteins is plenty to look at. If the data runs to thousands, raise the evidence level or narrow the scope and say so in the description, unless the user asked for the whole thing. Proteins no virus reaches show coverage, but they swamp a small network, so include them when coverage is the point.

## 2. The standard page

- The layout is force-directed (fcose). Proteins are circles, labelled with their name.
- Colour depends on kind and partners:
  - **Red:** viral proteins.
  - **Blue:** human proteins with at least one viral partner.
  - **Grey:** human proteins with only human partners, or none.
- Edge width follows `n_publications`.
- Clicking a protein or an interaction shows its details, an interaction's publications and methods included.
- Proteins can be dragged. **Save PNG** saves the whole network as it stands, dragged positions included, at 3× resolution, as `<name>.png`.

## 3. Adjusting the page

Edit only the `adjust` block near the end of the generated HTML:

```js
const adjust = {
  style: [
    { selector: "node[role = 'driver']", style: { shape: "triangle" } },
    { selector: "node[name = 'GPX4']", style: { "border-width": 3, "border-color": "#000" } },
    { selector: ".human-only", style: { display: "none" } },
  ],
  layout: { idealEdgeLength: 90 },
  legend: [["driver", "#d6332f"], ["suppressor", "#2f6fdb"]],
};
```

- **`style`**: [Cytoscape stylesheet](https://js.cytoscape.org/#style) entries, applied after the defaults, so they win.
  - Every protein field and attribute can be used in a selector.
  - The default classes are `.viral`, `.human` and `.human-only`.
- **`layout`**: options merged over the default fcose layout.
- **`legend`**: `[label, colour]` pairs that replace the default legend. Keep it in step with the colours.

Re-rendering overwrites the page, adjustments included. After changing the dataset, re-render, then apply the adjustments again.

**Check how it looks**, if a browser tool is available. Browser extensions usually refuse `file://` pages, so serve the directory:

```sh
uv run --no-project python -m http.server 8765 --bind 127.0.0.1 --directory <dir>
```

Open `http://127.0.0.1:8765/<name>.cytoscape.html` and take a screenshot. Read the console for errors, then adjust and reload. Stop the server when you are done.

## Report back

Give the path of the page, the protein and interaction counts, the evidence level in one line, and any adjustments made.
