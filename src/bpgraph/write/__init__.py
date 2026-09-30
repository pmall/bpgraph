"""The statements that write the graph, one module per part of the schema.

Each function takes a stream of rows, already prepared, and hands them to a
`GraphWriter`; nothing here reads a file or decides what a row holds.
"""
