from __future__ import annotations

import asyncio

import pytest

from edrader.broker import task_error_logger


class TestTaskErrorLogger:
    async def test_successful_task_does_not_raise(self) -> None:
        async def success() -> int:
            return 42

        task = asyncio.create_task(success())
        await task
        cb = task_error_logger("test", "test_event")
        cb(task)  # Should not raise

    async def test_cancelled_task_swallowed(self) -> None:
        async def never() -> None:
            await asyncio.Event().wait()

        task = asyncio.create_task(never())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        cb = task_error_logger("test", "test_event")
        cb(task)  # Should not raise

    async def test_failed_task_logs_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        async def fail() -> None:
            raise ValueError("boom")

        task = asyncio.create_task(fail())
        with pytest.raises(ValueError):
            await task
        cb = task_error_logger("test", "my_event_name")
        cb(task)
        captured = capsys.readouterr()
        assert "my_event_name" in captured.out

    async def test_failed_task_does_not_propagate(self) -> None:
        async def fail() -> None:
            raise RuntimeError("crash")

        task = asyncio.create_task(fail())
        with pytest.raises(RuntimeError):
            await task
        cb = task_error_logger("test", "test_event")
        cb(task)  # Should not raise
