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
        self._prune_task: "asyncio.Task | None" = None
        self.last_result: dict = {}
        self.last_prune: dict = {}
        self.next_fire_iso: str = ""
        self.next_prune_iso: str = ""

    def start(self) -> None:
        """The brief is optional; RETENTION IS NOT.

        Defect D6: the prune used to be one line inside the brief loop, so it was
        gated on `brief_enabled` and shared a `try` with the brief. Turning briefs off
        — or a brief raising — silently turned off retention, and a disk filling up is
        not a failure anyone would trace back to BRIEF_ENABLED. It is its own task
        now, started unconditionally."""
        if self._task is None and CONFIG.brief_enabled:
            self._task = asyncio.create_task(self._run(), name="brief-scheduler")
        if self._prune_task is None:
            self._prune_task = asyncio.create_task(self._run_prune(), name="prune-scheduler")

    async def stop(self) -> None:
        tasks = [self._task, self._prune_task]
        self._task = self._prune_task = None
        for task in tasks:
            if task is None or task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:  # noqa: BLE001
                log.warning("scheduler task ended with: %s", e)

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

    async def _run_prune(self) -> None:
        """Retention, on its own clock and its own error boundary.

        One hour after the brief hour, so the two do not contend for the same SQLite
        write lock at exactly the same second."""
        tz = ZoneInfo(CONFIG.brief_tz)
        prune_hour = (CONFIG.brief_hour_local + 1) % 24
        while True:
            now = datetime.now(tz)
            target = next_fire(now, prune_hour, CONFIG.brief_tz)
            self.next_prune_iso = target.isoformat()
            try:
                await asyncio.sleep(max(1.0, (target - now).total_seconds()))
                self.last_prune = await asyncio.to_thread(prune_once)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — a failed prune never kills the loop
                log.warning("scheduled prune failed: %s", e)
                await asyncio.sleep(60)


def prune_once(store=None, now_ms_: "int | None" = None) -> dict:
    """Delete everything past the retention horizon and LOG THE COUNTS.

    Riding the daily brief task rather than a timer of its own means the prune happens
    exactly once a day for the same reason the brief does, and there is no second
    schedule to drift. The counts are logged because a prune that silently removes
    nothing and a prune that silently removes everything look identical otherwise."""
    from .store import get_store, now_ms

    store = store or get_store()
    cutoff = (now_ms_ or now_ms()) - CONFIG.retention_days * 24 * 60 * 60 * 1000
    try:
        counts = store.prune(cutoff)
    except Exception as e:  # noqa: BLE001 — a failed prune never stops the brief
        log.warning("retention prune failed: %s", type(e).__name__)
        return {"error": type(e).__name__}
    log.info("retention prune (cutoff %s, %s days): %s", cutoff, CONFIG.retention_days,
             ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    counts["cutoff_ms"] = cutoff
    counts["retention_days"] = CONFIG.retention_days
    return counts


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
