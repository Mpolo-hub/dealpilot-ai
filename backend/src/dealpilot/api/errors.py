"""Shared error format for /v1 paths (spec 002 section 3.5, D12, D13).

FastAPI exception handlers are app-wide, so each handler checks the path. Outside /v1
(including /health) the response is exactly FastAPI's default.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dealpilot.analytics.dataset import ENV_VAR, DataUnavailable

DATA_UNAVAILABLE_MESSAGE = (
    "Sales data is not available. From the project root, run "
    "`backend\\.venv\\Scripts\\python.exe -m dealpilot.data.generate --out data/raw`, "
    f"or set {ENV_VAR} to a folder made by the generator."
)
# Public demo mode (spec 014, S1-D15): no local command, path or detail is shown.
PUBLIC_DATA_UNAVAILABLE_MESSAGE = "The demo data is temporarily unavailable."
_HTTP_CODES = {404: ("not_found", "No such route."),
               405: ("method_not_allowed", "This route does not support this method.")}


class APIError(Exception):
    """An error with a code from section 3.5. Raised only by /v1 routes."""

    def __init__(self, status_code: int, code: str, message: str,
                 details: list[dict] | None = None) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message
        self.details = details or []


def detail(parameter: str | None, value: str | None, reason: str) -> dict:
    return {"parameter": parameter, "value": value, "reason": reason}


def error_response(status_code: int, code: str, message: str, details: list[dict] | None = None,
                   headers: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or []}}
    return JSONResponse(body, status_code=status_code, headers=headers)


def is_v1(request: Request) -> bool:
    path = request.url.path
    return path == "/v1" or path.startswith("/v1/")


def install_error_handlers(app: FastAPI, public: bool = False) -> None:
    @app.exception_handler(APIError)
    async def api_error(request: Request, exc: APIError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(DataUnavailable)
    async def data_unavailable(request: Request, exc: DataUnavailable) -> JSONResponse:
        if public:
            return error_response(503, "data_unavailable", PUBLIC_DATA_UNAVAILABLE_MESSAGE)
        details = [detail(ENV_VAR, exc.configured, reason) for reason in exc.reasons]
        return error_response(503, "data_unavailable", DATA_UNAVAILABLE_MESSAGE, details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        if not is_v1(request):
            return await http_exception_handler(request, exc)
        code, message = _HTTP_CODES.get(exc.status_code, ("internal_error", "Unexpected error."))
        return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if not is_v1(request):
            return await request_validation_exception_handler(request, exc)
        details = [detail(str(e["loc"][-1]), None, e["msg"]) for e in exc.errors()]
        return error_response(422, "invalid_parameter", "The request is invalid.", details)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        if not is_v1(request):
            return PlainTextResponse("Internal Server Error", status_code=500)  # FastAPI default
        return error_response(500, "internal_error", "An unexpected error occurred.")
