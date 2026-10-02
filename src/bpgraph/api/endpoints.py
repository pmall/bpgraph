"""Every endpoint, with what serving it takes: its parameters as a model, and
its result as a type, rendered as text by `text.py`.

Serving adds `max_tokens` to every endpoint: a result larger than it is
refused with its size, never cut, so the caller decides what to ask instead.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from bpgraph.api import raw, sequences
from bpgraph.api.base import Backend, Rows
from bpgraph.api.text import render

CHARS_PER_TOKEN = 3
"""How a result's size is estimated in tokens: its text, three characters to
a token, which errs towards more tokens."""

MAX_TOKENS = 25_000

MaxTokens = Annotated[
    int,
    Field(
        ge=1,
        description="Refuse a result estimated larger, giving its size instead.",
    ),
]


class TooLarge(ValueError):
    """A result over the caller's `max_tokens`."""


FUNCTIONS: tuple[Callable[..., Any], ...] = (
    raw.schema,
    raw.cypher,
    sequences.human_sequences,
    sequences.viral_sequences,
    sequences.observed_sequences,
)


@dataclass(frozen=True, slots=True)
class Endpoint:
    function: Callable[..., Any]
    signature: inspect.Signature
    """The function's, without the backend: what a caller passes."""
    parameters: type[BaseModel]

    @property
    def name(self) -> str:
        return self.function.__name__

    @property
    def description(self) -> str:
        return inspect.cleandoc(self.function.__doc__ or "")

    def answer(self, backend: Backend, parameters: BaseModel) -> str:
        """The result as text, unless it is over the call's `max_tokens`."""
        arguments = dict(parameters)
        max_tokens = arguments.pop("max_tokens")
        result = self.function(backend, **arguments)
        answer = render(result)
        tokens = len(answer) // CHARS_PER_TOKEN
        if tokens <= max_tokens:
            return answer
        size = (
            f"the result is ~{tokens:,} tokens, over max_tokens {max_tokens:,} "
            f"(estimated at {CHARS_PER_TOKEN} characters per token)"
        )
        if isinstance(result, Rows) and result.rows:
            per_row = tokens // len(result.rows)
            size += (
                f": {len(result.rows):,} rows of ~{per_row:,} tokens, "
                f"of {result.total:,} in total"
            )
        raise TooLarge(size)


def _endpoint(function: Callable[..., Any]) -> Endpoint:
    signature = inspect.signature(function, eval_str=True)
    _, *parameters = signature.parameters.values()
    parameters.append(
        inspect.Parameter(
            "max_tokens",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=MAX_TOKENS,
            annotation=MaxTokens,
        )
    )
    fields: dict[str, Any] = {
        p.name: (p.annotation, ... if p.default is p.empty else p.default)
        for p in parameters
    }
    return Endpoint(
        function=function,
        signature=signature.replace(parameters=parameters),
        parameters=create_model(
            f"{function.__name__}_parameters",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        ),
    )


ENDPOINTS: dict[str, Endpoint] = {f.__name__: _endpoint(f) for f in FUNCTIONS}
