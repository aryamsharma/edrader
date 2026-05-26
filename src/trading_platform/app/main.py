import asyncio
import signal
from pathlib import Path

from trading_platform.app.bootstrap import Application


async def main() -> None:
    config_path = Path("configs/default.yaml")
    app = Application.from_config_path(config_path)

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    await app.startup()

    try:
        await stop_event.wait()
    finally:
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
