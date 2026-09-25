---
name: network-view
description: Draw a subnetwork of the bpgraph protein–protein interaction graph as an interactive HTML page — e.g. one viral family's interactions with a topic such as ferroptosis, at a chosen evidence level. Use when asked to visualize, draw, plot or show a network, subnetwork or interactome from the graph.
---

# Network view

Three steps:

1. **Gather the dataset.** Query the graph, choose what the network holds, and write it to `<name>.json`. This is your judgment.
2. **Render it.** Run `uv run bpgraph-network <name>.json`. It writes a standard page, `<name>.cytoscape.html`, beside the JSON. The script never touches the database, and you never write a page from scratch. Every network starts from the same look, so networks can be compared.
3. **Adjust the page**, if the network calls for it. Change colours, labels, shapes or layout in the page's `adjust` block, and nowhere else.

## Inputs

- **What to draw**, e.g. ferroptosis × Flaviviridae. Ask if it is unclear.
- **Evidence level.** The default is the **golden dataset**: an interaction backed by at least 2 distinct publications **or** at least 2 distinct detection methods. Apply it to each interaction on its own, meaning one viral protein with one human protein. Never add up evidence across proteins to get over the bar.
- **Destination:** wherever the user asks. Ask if they haven't said. Name the files after the network, e.g. `ferroptosis-flaviviridae.json`.

## 1. The dataset

Query the graph through whatever access the environment provides, such as the MCP server. The schema is in `docs/schema.md`. Then write:

```json
{
  "title": "Ferroptosis × Flaviviridae (golden)",
  "description": "One or two sentences: what is drawn, and the evidence rule applied.",
  "proteins": [
    {"id": "P36969", "name": "GPX4", "kind": "human",
     "description": "Phospholipid hydroperoxide glutathione peroxidase",
     "taxon_name": "Homo sapiens", "attributes": {"role": "suppressor"}},
    {"id": "P27958:1973-2419", "name": "NS5A", "kind": "viral",
     "description": "Genome polyprotein", "taxon_name": "Orthohepacivirus hominis"}
  ],
  "interactions": [
    {"source": "P36969", "target": "P27958:1973-2419", "n_publications": 1, "n_methods": 2}
  ]
}
```

- `id` is the graph's protein `id`. `kind` is `human` or `viral`, taken from the protein's label.
- `attributes` is optional. Use it for anything else worth showing or styling by, such as the topic's `role` or the viral family. It appears when a protein is clicked, and the page can style by it.
- An interaction connects two listed proteins, and each pair appears once. The counters come from the graph's `:Interaction`.
- The renderer refuses a file that breaks these rules.

Write the `description` for a reader who has not seen how the data was gathered. Name the topic, the family, the evidence rule, and anything included beyond the direct interactions, such as HH edges, untargeted topic proteins or one-hop partners.

**Keep it readable.** A few hundred proteins is plenty to look at. If the data runs to thousands, tighten the evidence level or the scope and say so in the description, unless the user asked for the whole thing. Proteins no virus reaches show coverage, but they swamp a small network, so include them when coverage is the point.

## 2. The standard page

- The layout is force-directed (fcose). Proteins are circles, labelled with their name.
- Colour depends on kind and partners:
  - **Red:** viral proteins.
  - **Blue:** human proteins with at least one viral partner.
  - **Grey:** human proteins with only human partners, or none.
- Edge width follows `n_publications`.
- Clicking a protein or an interaction shows its details.
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

Give the path of the page, the protein and interaction counts, the evidence rule in one line, and any adjustments made.
