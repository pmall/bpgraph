"""Results as text. Every token an agent reads is one it cannot spend
exploring, so a list is a table: a line counting its rows, a header, and one
tab-separated line per row, with no column every row leaves empty.

A cell holds a list as its items joined by `;`, and a mapping as `key=value`
pairs joined by `,`. Tabs and line breaks in text become spaces, and a
paragraph break becomes ` ¶ `, so a row stays on one line.
"""

from collections.abc import Mapping, Sequence

from pydantic import BaseModel

from bpgraph.api.base import Rows


def cell(value: object) -> str:
    match value:
        case None:
            return ""
        case bool():
            return "true" if value else "false"
        case float():
            return f"{value:.4g}"
        case BaseModel():
            return cell(value.model_dump(mode="json"))
        case Mapping():
            return ",".join(f"{k}={cell(v)}" for k, v in value.items())
        case list() | tuple():
            return ";".join(cell(v) for v in value)
        case _:
            text = str(value).replace("\t", " ").replace("\r", "")
            return text.replace("\n\n", " ¶ ").replace("\n", " ")


def _plain(row: object) -> Mapping[str, object]:
    if isinstance(row, BaseModel):
        return dict(row)
    if isinstance(row, Mapping):
        return row
    return {"value": row}


def table(rows: Sequence[object]) -> str:
    """A header and one line per row, without the columns no row fills."""
    plain = [_plain(row) for row in rows]
    columns = [
        column
        for column in dict.fromkeys(c for row in plain for c in row)
        if any(cell(row.get(column)) for row in plain)
    ]
    lines = ["\t".join(columns)]
    lines += ["\t".join(cell(row.get(c)) for c in columns) for row in plain]
    return "\n".join(lines)


def count(shown: int, total: int) -> str:
    noun = "row" if total == 1 else "rows"
    return f"{total} {noun}" if shown == total else f"{shown} of {total} {noun}"


def render(result: object) -> str:
    """A result as the text an agent reads."""
    match result:
        case str():
            return result
        case Rows():
            head = count(len(result.rows), result.total)
            return f"{head}\n{table(result.rows)}" if result.rows else head
        case _:
            return cell(result)
