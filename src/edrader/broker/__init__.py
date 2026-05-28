from __future__ import annotations

import asyncio
from collections.abc import Callable

from edrader.monitoring.logging import get_logger


def task_error_logger(
    logger_name: str,
    event_name: str,
) -> Callable[[asyncio.Task[None]], None]:
    logger = get_logger(logger_name)

    def _log(task: asyncio.Task[None]) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(event_name, error=str(e))

    return _log
