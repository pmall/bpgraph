"""The statements that write the graph, one module per part of the schema.

Each function takes a stream of rows, already prepared, and hands them to a
`GraphWriter`; nothing here reads a file or decides what a row holds.

Nothing pre-exists in a fresh graph, so a node is always a `CREATE`: `MERGE`
would buy nothing and cost a lookup per row, and the preparation has made every
row distinct. A relationship is created between ends found by their natural
keys, save a peptide's `:FROM` and `:BINDS`, merged, since many reports link
one peptide to one protein. A node with no key is written in one statement
with the edges that make it what it is, its parts nested in its row, since
nothing could find it again. A statement unwinding a row's parts gathers them
back to one line per row before it returns, and counts only the rows whose
parts all came through, so that `GraphWriter.write` reports a row that lost
one.
"""
