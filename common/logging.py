"""Structured logging configuration and correlation ID helpers."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Callable

import structlog
from fastapi import Request


def configure_logging() -> None:
    """Configure structlog for JSON logging."""

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=log_level, format="%(message)s")

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(log_level)),
        cache_logger_on_first_use=True,
    )


def get_correlation_id(request: Request) -> str:
    """Resolve or generate a correlation ID for a request."""

    incoming = request.headers.get("x-correlation-id")
    return incoming or str(uuid.uuid4())


def correlation_middleware(app_logger: structlog.BoundLogger) -> Callable:
    """Return a middleware that injects correlation IDs into logs."""

    async def _middleware(request: Request, call_next):
        correlation_id = get_correlation_id(request)
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        app_logger.info(
            "request_completed",
            path=request.url.path,
            method=request.method,
            correlation_id=correlation_id,
        )
        return response

    return _middleware
