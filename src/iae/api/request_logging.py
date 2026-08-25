"""Log inbound request / response JSON payloads to the uvicorn terminal."""

from __future__ import annotations

import json
import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("iae.http")

_SKIP_PATH_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
)
_MAX_CHARS = 6000


def _preview(raw: bytes) -> str:
    if not raw:
        return "(empty)"
    text = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
        text = json.dumps(parsed, indent=2, ensure_ascii=False, default=str)
    except (json.JSONDecodeError, TypeError):
        pass
    if len(text) > _MAX_CHARS:
        return text[:_MAX_CHARS] + f"\n… truncated ({len(text)} chars total)"
    return text


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    """Print method/path + request body + response status/body for API calls."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
            return await call_next(request)

        req_body = await request.body()

        async def receive() -> dict:
            return {"type": "http.request", "body": req_body, "more_body": False}

        request = Request(request.scope, receive)

        query = f"?{request.url.query}" if request.url.query else ""
        logger.info(
            "→ %s %s%s\nREQUEST BODY:\n%s",
            request.method,
            path,
            query,
            _preview(req_body),
        )

        response = await call_next(request)

        resp_chunks: list[bytes] = []
        async for chunk in response.body_iterator:
            resp_chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
        resp_body = b"".join(resp_chunks)

        logger.info(
            "← %s %s%s  status=%s\nRESPONSE BODY:\n%s",
            request.method,
            path,
            query,
            response.status_code,
            _preview(resp_body),
        )

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=resp_body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
            background=response.background,
        )
