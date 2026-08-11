from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Literal
from uuid import uuid4

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sombreado.logging import get_logger

ResponseDurationClass = Literal["fast", "medium", "slow"]

REQUEST_ID_STATE_KEY = "request_id"

logger = get_logger(__name__)


def classify_response_duration(
    duration_ms: float,
    *,
    fast_below_ms: float,
    slow_at_or_above_ms: float,
) -> ResponseDurationClass:
    if duration_ms < fast_below_ms:
        return "fast"
    if duration_ms < slow_at_or_above_ms:
        return "medium"
    return "slow"


def format_request_access_log_message(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    duration_class: ResponseDurationClass,
) -> str:
    return (
        f"request_id={request_id} method={method} path={path} "
        f"status={status_code} duration_ms={int(duration_ms)} duration_class={duration_class}"
    )


def access_log_level(duration_class: ResponseDurationClass) -> int:
    return logging.WARNING if duration_class == "slow" else logging.INFO


class RequestAccessLogMiddleware:
    """Pure ASGI middleware that records one Request Access Log per HTTP response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        fast_below_ms: float,
        slow_at_or_above_ms: float,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.app = app
        self._fast_below_ms = fast_below_ms
        self._slow_at_or_above_ms = slow_at_or_above_ms
        self._clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        request_id = str(uuid4())
        setattr(request.state, REQUEST_ID_STATE_KEY, request_id)
        started = self._clock()
        status_code: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if status_code is not None:
                # Classify on the same integer ms that appears in the log line.
                duration_ms = round((self._clock() - started) * 1000)
                duration_class = classify_response_duration(
                    duration_ms,
                    fast_below_ms=self._fast_below_ms,
                    slow_at_or_above_ms=self._slow_at_or_above_ms,
                )
                logger.log(
                    access_log_level(duration_class),
                    format_request_access_log_message(
                        request_id=request_id,
                        method=request.method,
                        path=request.url.path,
                        status_code=status_code,
                        duration_ms=duration_ms,
                        duration_class=duration_class,
                    ),
                )
