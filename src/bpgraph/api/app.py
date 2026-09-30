"""The API server, `bpgraph-api`: one `POST /<name>` per endpoint.

A request's JSON body holds the endpoint's parameters, and the response is
its result as JSON. `GET /` lists the endpoints. Bad parameters answer 422, a
query the graph refuses or a question with no answer 400, a vault not
published 503. Not exposed: only the MCP server reaches it.
"""

import os
from collections.abc import Awaitable, Callable

from pydantic import ValidationError
from redis.exceptions import ResponseError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bpgraph.api.base import Backend
from bpgraph.api.endpoints import ENDPOINTS, Endpoint
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
            result = await run_in_threadpool(
                endpoint.function, backend, **dict(parameters)
            )
        except (ResponseError, ValueError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        except FileNotFoundError as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        return Response(
            endpoint.result.dump_json(result), media_type="application/json"
        )

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
    """`bpgraph-api`: serve until stopped, on `API_HOST` and `API_PORT`."""
    import uvicorn

    config = Config.from_env()
    backend = Backend(
        graph=connect(config).select_graph(config.live_graph), vault=config.vault
    )
    uvicorn.run(
        application(backend),
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "8000")),
    )
