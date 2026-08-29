"""Continuous oracle: re-forecast the world on an interval when enabled."""
from __future__ import annotations

import asyncio
import logging

from .config import CONFIG
from .state import STATE

log = logging.getLogger("pythia.loop")


async def _cancel(task: "asyncio.Task | None") -> None:
    """Cancel a background task and wait for it — no dangling tasks on shutdown."""
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("task %s ended with: %s", task.get_name(), e)


class SenseLoop:
    """Keeps live events fresh (no LLM) so the agent view + chat always see 'now'.
    Also hosts the resolution sweep — the brief is freshest right after a refresh."""
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._last_resolve = 0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="sense-loop")

    async def _run(self) -> None:
        from .models import now_ms
        from .pipeline import refresh_world
        while True:
            try:
                if not STATE.generating:
                    await refresh_world()
                    # The resolver is FORECAST work. In monitor mode it is not merely
                    # given a huge interval — it is never imported or called.
                    if CONFIG.research_mode and now_ms() - self._last_resolve >= CONFIG.resolve_interval_sec * 1000:
                        from .resolver import resolve_due
                        self._last_resolve = now_ms()
                        await resolve_due()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("sense loop failed: %s", e)
            await asyncio.sleep(CONFIG.sense_interval_sec)

    async def stop(self) -> None:
        await _cancel(self._task)
        self._task = None


class OracleLoop:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="oracle-loop")

    async def _run(self) -> None:
        while True:
            try:
                if STATE.loop_enabled and not STATE.generating:
                    from .pipeline import run_prediction
                    await run_prediction(trigger="loop")
                    await asyncio.sleep(CONFIG.loop_interval_sec)
                else:
                    await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("loop iteration failed: %s", e)
                await asyncio.sleep(10)

    async def stop(self) -> None:
        await _cancel(self._task)
        self._task = None


LOOP = OracleLoop()
SENSE = SenseLoop()
