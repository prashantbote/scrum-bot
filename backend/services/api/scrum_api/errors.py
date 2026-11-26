"""RFC 7807 problem+json errors (plan §6.2)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)
PROBLEM = "application/problem+json"


class Problem(Exception):
    def __init__(
        self, status: int, title: str, detail: str | None = None, errors: list[dict[str, str]] | None = None
    ) -> None:
        super().__init__(detail or title)
        self.status, self.title, self.detail, self.errors = status, title, detail, errors


def not_found(what: str = "Resource") -> Problem:
    return Problem(404, f"{what} not found")


def forbidden(detail: str = "Your role can't do this.") -> Problem:
    return Problem(403, "Forbidden", detail)


def invalid(field: str, message: str) -> Problem:
    return Problem(422, "Validation failed", None, [{"field": field, "message": message}])


def _body(
    status: int, title: str, detail: str | None = None, errors: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"title": title, "status": status}
    if detail:
        body["detail"] = detail
    if errors:
        body["errors"] = errors
    return body


def install(app: FastAPI) -> None:
    @app.exception_handler(Problem)
    async def _problem(_: Request, exc: Problem) -> JSONResponse:
        return JSONResponse(
            _body(exc.status, exc.title, exc.detail, exc.errors), status_code=exc.status, media_type=PROBLEM
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for e in exc.errors():
            loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
            errors.append({"field": ".".join(loc) or "body", "message": str(e.get("msg", "Invalid value"))})
        return JSONResponse(_body(422, "Validation failed", None, errors), status_code=422, media_type=PROBLEM)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(_body(exc.status_code, str(exc.detail)), status_code=exc.status_code, media_type=PROBLEM)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            _body(500, "Internal error", "Something went wrong on our side."), status_code=500, media_type=PROBLEM
        )
