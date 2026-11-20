"""The public error shape. Claims live in messages; this is the contract."""

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """An HTTP error with a stable code and, when known, the run id."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        *,
        run_id: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.run_id = run_id


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code, "run_id": exc.run_id},
    )
