import logging
import sys
from typing import Any

import structlog


def setup_logging(log_level: str = "DEBUG", log_file: str = "") -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if log_file:
        processors.append(structlog.processors.JSONRenderer())
        logger_factory = structlog.PrintLoggerFactory(file=open(log_file, "a"))  # noqa: SIM115
    else:
        processors.append(
            structlog.dev.ConsoleRenderer()
            if sys.stderr.isatty()
            else structlog.processors.JSONRenderer()
        )
        logger_factory = structlog.PrintLoggerFactory()

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.DEBUG)
        ),
        context_class=dict,
        logger_factory=logger_factory,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
