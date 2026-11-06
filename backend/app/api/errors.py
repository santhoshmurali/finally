"""Maps domain errors to HTTP status codes in one place."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.llm.client import LLMError
from app.market import UnsupportedTickerError
from app.portfolio import TradeRejectedError
from app.watchlist import AlreadyWatchedError, InvalidTickerError, NotWatchedError

STATUS_BY_ERROR: dict[type[Exception], int] = {
    TradeRejectedError: 400,
    UnsupportedTickerError: 400,
    InvalidTickerError: 400,
    AlreadyWatchedError: 409,
    NotWatchedError: 404,
    LLMError: 503,
}


def register_error_handlers(app: FastAPI) -> None:
    """Answer each mapped domain error with its status and `{"detail": message}`."""
    for error_type, status_code in STATUS_BY_ERROR.items():
        app.add_exception_handler(error_type, _handler(status_code))


def _handler(status_code: int):
    async def handle(_request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=status_code)

    return handle
