"""Logging estructurado JSON con correlation id vía contextvars."""
from __future__ import annotations

import logging

import structlog

from shared.config import LogLevel


def configure_logging(level: LogLevel) -> None:
    logging.basicConfig(level=getattr(logging, level.value), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.value)),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    return structlog.get_logger(name)
