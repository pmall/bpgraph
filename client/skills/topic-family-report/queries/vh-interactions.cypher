// The family's VH interactions with the topic's proteins.
// $accessions: the topic's Swiss-Prot accessions. $family: the :Family name.
// $golden: true keeps the golden dataset, false every interaction.
MATCH (h:Human) WHERE h.accession IN $accessions
WITH h
MATCH (h)-[e:INTERACTS_WITH]-(v:Viral)-[:IN_TAXON]->(t:Virus)-[:PARENT]->(f:Family)
WITH h, e, v, t, f
WHERE f.name = $family AND (NOT $golden OR e.n_publications >= 2 OR e.n_methods >= 2)
RETURN t.name AS virus, v.ncbi_taxon_id AS ncbi_taxon_id, v.name AS viral_protein,
       h.accession AS accession, h.name AS gene,
       e.n_publications AS n_publications, e.n_methods AS n_methods,
       e.n_descriptions AS n_descriptions, e.n_peptides AS n_peptides
ORDER BY virus, viral_protein, gene
