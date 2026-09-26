"""Reading the tab-separated files a run holds, with every error located.

Every file a build reads is TSV — the export, and everything fetched beside it.
One line is one row and a tab is always a separator: quoting is off, so a
double quote in an abstract is text like any other. A cell holding a tab or a
newline of its own no longer parses, and is caught by its line number rather
than silently swallowing the rows around it.
"""

import csv
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails


class LoadError(ValueError):
    """A run is missing something, or holds something it should not."""


@dataclass(frozen=True, slots=True)
class Cursor:
    """Where we are, so every error names a file and a line."""

    path: Path
    line: int

    def fail(self, message: str) -> LoadError:
        return LoadError(f"{self.path.name}:{self.line}: {message}")


def rows(path: Path) -> Iterator[tuple[Cursor, Mapping[str, str]]]:
    """The rows of one file. A file that is not there is an error: which files
    a run may do without is its loader's decision, not this one's."""
    if not path.exists():
        raise LoadError(f"{path} is missing")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        header = next(reader, None)
        if header is None:
            raise LoadError(f"{path.name} has no header row")
        columns = [column.strip() for column in header]
        for offset, values in enumerate(reader, start=2):
            if not values:
                continue
            cursor = Cursor(path, offset)
            if len(values) != len(columns):
                raise cursor.fail(
                    f"{len(values)} columns, not {len(columns)}: a cell holds a tab "
                    "or a newline of its own"
                )
            yield (
                cursor,
                {
                    column: value.strip()
                    for column, value in zip(columns, values, strict=True)
                },
            )


def text(cursor: Cursor, row: Mapping[str, str], column: str) -> str:
    if column not in row:
        raise cursor.fail(f"missing column {column!r}")
    return row[column]


def required(cursor: Cursor, row: Mapping[str, str], column: str) -> str:
    value = text(cursor, row, column)
    if not value:
        raise cursor.fail(f"{column} is empty")
    return value


def integer(cursor: Cursor, row: Mapping[str, str], column: str) -> int:
    value = required(cursor, row, column)
    try:
        return int(value)
    except ValueError:
        raise cursor.fail(f"{column} is not a whole number: {value!r}") from None


def listed(cursor: Cursor, row: Mapping[str, str], column: str) -> tuple[str, ...]:
    """A `;`-separated cell, as its non-empty items."""
    return tuple(
        item.strip() for item in text(cursor, row, column).split(";") if item.strip()
    )


def choice[T: StrEnum](
    cursor: Cursor, row: Mapping[str, str], column: str, options: type[T]
) -> T:
    value = required(cursor, row, column)
    try:
        return options(value)
    except ValueError:
        allowed = ", ".join(sorted(member.value for member in options))
        raise cursor.fail(f"{column} must be one of {allowed}, not {value!r}") from None


def make[T: BaseModel](cursor: Cursor, model: type[T], **fields: object) -> T:
    """Build a model, turning a validation failure into a located error.

    The models carry the rules a single row can break; this is what attaches a
    file and a line number to them, so a file is fixable by looking at it.
    """
    try:
        return model(**fields)
    except ValidationError as error:
        raise cursor.fail("; ".join(_describe(p) for p in error.errors())) from None


def _describe(problem: ErrorDetails) -> str:
    """One pydantic problem, as a line someone editing a spreadsheet can act on."""
    column = ".".join(str(part) for part in problem["loc"])
    message = problem["msg"].removeprefix("Value error, ")
    return f"{column}: {message}" if column else message
