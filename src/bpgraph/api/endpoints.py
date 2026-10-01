"""Every endpoint, with what serving it takes: its parameters as a model, and
its result as a type to serialize and validate.

Serving adds `max_tokens` to every endpoint: a result larger than it is
refused with its size, never cut, so the caller decides what to ask instead.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model

from bpgraph.api import (
    go,
    interactions,
    peptides,
    proteins,
    publications,
    raw,
    sequences,
)
from bpgraph.api.base import Backend, Rows

CHARS_PER_TOKEN = 3
"""How a result's size is estimated in tokens: its JSON, three characters to
a token, which errs towards more tokens."""

MAX_TOKENS = 25_000

MaxTokens = Annotated[
    int,
    Field(
        ge=1,
        description="Refuse a result estimated larger than this many tokens, "
        "rather than return it; the refusal gives its size and row counts. "
        "Raise it when your context can take more.",
    ),
]


class TooLarge(ValueError):
    """A result over the caller's `max_tokens`."""


FUNCTIONS: tuple[Callable[..., Any], ...] = (
    proteins.overview,
    proteins.viruses,
    proteins.viral_proteins,
    proteins.find_proteins,
    proteins.proteins,
    interactions.partners,
    interactions.vh_interactions,
    interactions.hh_interactions,
    interactions.neighbours,
    interactions.indirect_reach,
    interactions.coverage,
    interactions.evidence,
    peptides.peptides,
    peptides.peptide,
    publications.publications,
    publications.publication_content,
    publications.search_publications,
    go.go_annotations,
    go.go_rollup,
    go.search_go_terms,
    go.go_term_proteins,
    sequences.human_sequences,
    sequences.viral_sequences,
    raw.schema,
    raw.cypher,
)


@dataclass(frozen=True, slots=True)
class Endpoint:
    function: Callable[..., Any]
    signature: inspect.Signature
    """The function's, without the backend: what a caller passes."""
    parameters: type[BaseModel]
    result: TypeAdapter[Any]

    @property
    def name(self) -> str:
        return self.function.__name__

    @property
    def description(self) -> str:
        return inspect.cleandoc(self.function.__doc__ or "")

    def answer(self, backend: Backend, parameters: BaseModel) -> bytes:
        """The result as JSON, unless it is over the call's `max_tokens`."""
        arguments = dict(parameters)
        max_tokens = arguments.pop("max_tokens")
        result = self.function(backend, **arguments)
        answer = self.result.dump_json(result)
        tokens = len(answer) // CHARS_PER_TOKEN
        if tokens <= max_tokens:
            return answer
        size = (
            f"the result is ~{tokens:,} tokens, over max_tokens {max_tokens:,} "
            f"(estimated at {CHARS_PER_TOKEN} characters of JSON per token)"
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
        result=TypeAdapter(signature.return_annotation),
    )


ENDPOINTS: dict[str, Endpoint] = {f.__name__: _endpoint(f) for f in FUNCTIONS}
