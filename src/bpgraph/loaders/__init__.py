"""Preparing a run for a build: reading every silo into the files the graph is
written from, and checking them on the way. Nothing here touches the database.

`export` reads the curation export; `curated` turns its description files into
curated rows; `host` merges the human ones onto IntAct; `viral` assembles the
viral proteins; `peptides` places the peptides; `run` puts them together.
Every step reads and writes files a line at a time, sorted on disk where two
of them meet — see `bpgraph.files`.
"""
