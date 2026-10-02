"""The query API: the graph through its schema and read-only Cypher, and what
only the vaults hold, one endpoint each.

Every endpoint is a typed function taking the `Backend` first, then its
parameters. `endpoints.ENDPOINTS` lists them; `app.py` serves each at its own
path, and the MCP server mirrors each as a tool of the same name, signature
and description. The API is the only thing that reaches the graph and the
vaults; nothing it runs writes.
"""
