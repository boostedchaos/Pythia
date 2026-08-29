"""Fire the daily brief at BRIEF_HOUR_LOCAL in BRIEF_TZ.

Local time, not UTC: the brief is read at breakfast, and a UTC schedule would drift
an hour twice a year. `zoneinfo` does the DST arithmetic.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import CONFIG

log = logging.getLogger("pythia.monitor.schedule")


def next_fire(after: datetime, hour: int, tz_name: str) -> datetime:
    """The next occurrence of `hour`:00 local, strictly after `after`."""
    tz = ZoneInfo(tz_name)
    local = after.astimezone(tz)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target = (local + timedelta(days=1)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
    return target


class BriefScheduler:
    """One asyncio task, cancelled on shutdown like every other Phase 0 task."""

    def __init__(self) -> None:
        self._task: "asyncio.Task | None" = None
        self.last_result: dict = {}
        self.next_fire_iso: str = ""

    def start(self) -> None:
        if self._task is None and CONFIG.brief_enabled:
            self._task = asyncio.create_task(self._run(), name="brief-scheduler")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("brief scheduler ended with: %s", e)

    async def _run(self) -> None:
        tz = ZoneInfo(CONFIG.brief_tz)
        while True:
            now = datetime.now(tz)
            target = next_fire(now, CONFIG.brief_hour_local, CONFIG.brief_tz)
            self.next_fire_iso = target.isoformat()
            log.info("next daily brief at %s", self.next_fire_iso)
            try:
                await asyncio.sleep(max(1.0, (target - now).total_seconds()))
                self.last_result = await run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — a bad day never kills the schedule
                log.warning("scheduled brief failed: %s", e)
                await asyncio.sleep(60)


async def run_once() -> dict:
    """Collect, then brief. Sharing one pass means the brief's coverage warning
    names the sources that actually failed on the run it is describing."""
    from .brief import run_brief
    from .collect import collect_once

    runs: list = []
    try:
        runs = await collect_once()
    except Exception as e:  # noqa: BLE001 — brief on what IS stored rather than nothing
        log.warning("collection before brief failed: %s", type(e).__name__)
    return await run_brief(adapter_runs=runs)


SCHEDULER = BriefScheduler()
