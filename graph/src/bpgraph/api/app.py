"""The API server, `bpgraph-api`: one `POST /<name>` per endpoint.

`bpgraph-api` serves until stopped, on `API_HOST` and `API_PORT`
(`127.0.0.1:8000` by default). It reads the live graph and the published
vaults where `bpgraph.config` finds them.

A request's JSON body holds the endpoint's parameters, and the response is
its result as text, as the agent reads it. `GET /` lists the endpoints, as
JSON. An error answers a JSON object, its `error` the message: bad parameters
422, a result over `max_tokens` 413, a query the graph refuses or a question
with no answer 400, a vault not published 503. Not exposed: only the MCP
server reaches it.
"""

import argparse
import os
from collections.abc import Awaitable, Callable

import uvicorn
from pydantic import ValidationError
from redis.exceptions import ResponseError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bpgraph.api.base import Backend
from bpgraph.api.endpoints import ENDPOINTS, Endpoint, TooLarge
from bpgraph.client import connect
from bpgraph.config import Config


def _handler(
    backend: Backend, endpoint: Endpoint
) -> Callable[[Request], Awaitable[Response]]:
    async def handle(request: Request) -> Response:
        try:
            body = await request.body()
            parameters = endpoint.parameters.model_validate_json(body or b"{}")
        except ValidationError as error:
            return JSONResponse({"error": str(error)}, status_code=422)
        try:
            answer = await run_in_threadpool(endpoint.answer, backend, parameters)
        except TooLarge as error:
            return JSONResponse({"error": str(error)}, status_code=413)
        except (ResponseError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except FileNotFoundError as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        return Response(answer, media_type="text/plain; charset=utf-8")

    return handle


async def index(request: Request) -> Response:
    return JSONResponse(
        [{"name": e.name, "description": e.description} for e in ENDPOINTS.values()]
    )


def application(backend: Backend) -> Starlette:
    return Starlette(
        routes=[
            Route("/", index, methods=["GET"]),
            *(
                Route(f"/{e.name}", _handler(backend, e), methods=["POST"])
                for e in ENDPOINTS.values()
            ),
        ]
    )


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    ).parse_args()
    config = Config.from_env()
    backend = Backend(
        graph=connect(config).select_graph(config.live_graph), vault=config.vault
    )
    uvicorn.run(
        application(backend),
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
