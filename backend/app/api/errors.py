"""Every error response uses the one body docs/api.md defines: {"code", "message"}.

FastAPI's defaults are replaced: request validation is 400 (not 422 {"detail": [...]}),
unknown routes are not_found, and an unexpected exception is a 500 internal_error whose
message never contains a stack trace.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ApiError

logger = logging.getLogger(__name__)

INTERNAL_ERROR_MESSAGE = "Something went wrong on our side. Please try again later."


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message)


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0]
    name = first["loc"][-1] if first["loc"] else "request"
    code = "invalid_bbox" if name == "bbox" else "invalid_query"
    return error_response(400, code, f"{name}: {first['msg']}")


async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return error_response(404, "not_found", f"No endpoint at {request.url.path}.")
    if exc.status_code == 405:
        return error_response(405, "not_found", f"{request.method} is not supported; the API is read-only (GET).")
    if exc.status_code < 500:
        return error_response(exc.status_code, "invalid_query", str(exc.detail))
    return error_response(exc.status_code, "internal_error", INTERNAL_ERROR_MESSAGE)


class UnexpectedErrorMiddleware:
    """Turns an unhandled exception into a 500 internal_error body.

    A middleware rather than an Exception handler: Starlette runs those outside every
    middleware, so the 500 would miss its CORS headers and the browser would report a
    network error instead of internal_error. Plain ASGI (not @app.middleware), so
    responses pass through untouched and GZip still skips small bodies.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def send_tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope["method"], scope["path"])
            if started:
                raise
            await error_response(500, "internal_error", INTERNAL_ERROR_MESSAGE)(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    """Call before adding CORS, so the 500 middleware sits inside it."""
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_error)
    app.add_middleware(UnexpectedErrorMiddleware)
