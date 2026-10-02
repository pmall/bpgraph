// A topic x family network: the family's VH interactions with the topic's
// proteins, and the HH interactions among the topic's proteins, one row per
// interaction with both its proteins as the network's JSON names them.
// $accessions: the topic's Swiss-Prot accessions. $family: the :Family name.
// $golden: true keeps the golden dataset, false every interaction.
MATCH (h:Human) WHERE h.accession IN $accessions
WITH h
MATCH (h)-[e:INTERACTS_WITH]-(v:Viral)-[:IN_TAXON]->(t:Virus)-[:PARENT]->(f:Family)
WITH h, e, v, t, f
WHERE f.name = $family AND (NOT $golden OR e.n_publications >= 2 OR e.n_methods >= 2)
RETURN h.accession AS source, h.name AS source_name,
       h.description AS source_description, 'human' AS source_kind,
       'Homo sapiens' AS source_taxon,
       toString(v.ncbi_taxon_id) + ':' + v.name AS target, v.name AS target_name,
       '' AS target_description, 'viral' AS target_kind, t.name AS target_taxon,
       e.n_publications AS n_publications, e.n_methods AS n_methods
UNION
MATCH (h:Human) WHERE h.accession IN $accessions
WITH h
MATCH (h)-[e:INTERACTS_WITH]-(n:Human)
WITH h, e, n
WHERE n.accession IN $accessions AND h.accession < n.accession
  AND (NOT $golden OR e.n_publications >= 2 OR e.n_methods >= 2)
RETURN h.accession AS source, h.name AS source_name,
       h.description AS source_description, 'human' AS source_kind,
       'Homo sapiens' AS source_taxon,
       n.accession AS target, n.name AS target_name,
       n.description AS target_description, 'human' AS target_kind,
       'Homo sapiens' AS target_taxon,
       e.n_publications AS n_publications, e.n_methods AS n_methods
