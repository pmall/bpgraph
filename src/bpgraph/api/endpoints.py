"""Every endpoint, with what serving it takes: its parameters as a model, and
its result as a type to serialize and validate."""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, create_model

from bpgraph.api import (
    go,
    interactions,
    peptides,
    proteins,
    publications,
    raw,
    sequences,
)

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


def _endpoint(function: Callable[..., Any]) -> Endpoint:
    signature = inspect.signature(function, eval_str=True)
    _, *parameters = signature.parameters.values()
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
