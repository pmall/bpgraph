"""The OBO flat-file format, as GO and PSI-MI both publish their ontologies.

A file is a header, then stanzas: a `[Term]` or `[Typedef]` heading followed by
`tag: value` lines. Only the reading is shared here; what a tag means is each
ontology's business.
"""

from collections.abc import Iterator, Mapping
from pathlib import Path

TERM = "[Term]"
"""The only stanza kind that carries a term. The file ends with typedefs."""

DANGLING = " ! "
"""OBO closes a reference with the target's name, for people to read."""


def target(value: str) -> str:
    """An OBO reference, without the name OBO closes it with."""
    return value.split(DANGLING)[0].strip()


def stanzas(path: Path) -> Iterator[tuple[str, Mapping[str, list[str]]]]:
    """The file's stanzas, each as its tag lines grouped by tag.

    A tag may repeat — `is_a` once per parent — so every one of them is a list.
    The header above the first stanza has no heading and is never yielded.
    """
    heading = ""
    fields: dict[str, list[str]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("["):
                if heading:
                    yield heading, fields
                heading, fields = stripped, {}
            elif ": " in stripped:
                tag, _, value = stripped.partition(": ")
                fields.setdefault(tag, []).append(value.strip())
    if heading:
        yield heading, fields
