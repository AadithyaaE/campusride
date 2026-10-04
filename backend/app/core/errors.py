"""Domain errors and their HTTP mapping.

Services raise these; routers never build HTTP errors by hand.
Response body: ``{"error": {"code": "...", "message": "..."}}``.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class CampusRideError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(CampusRideError):
    status_code = 404
    code = "not_found"


class ConflictError(CampusRideError):
    status_code = 409
    code = "conflict"


class AuthError(CampusRideError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(CampusRideError):
    status_code = 403
    code = "forbidden"


class CodedError(CampusRideError):
    """A rejection with a specific machine-readable ``code`` (e.g. ``trip_already_active``)."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ServiceUnavailableError(CampusRideError):
    status_code = 503
    code = "unavailable"


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CampusRideError)
    async def _handle(_: Request, exc: CampusRideError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthError) else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=headers,
        )
