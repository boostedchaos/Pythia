"""In-memory oracle state + async pub/sub for SSE."""
from __future__ import annotations

import asyncio
import json
from collections import OrderedDict
from typing import Any, Optional

from .config import CONFIG
from .models import Prediction, RunRecord, WorldBrief, now_ms


class EngineState:
    def __init__(self) -> None:
        self.predictions: list[Prediction] = []     # current forecast set
        self.world: Optional[WorldBrief] = None
        self.events: list = []                       # latest raw WorldEvents (for agents)
        self.runs: "OrderedDict[str, RunRecord]" = OrderedDict()
        self.generating: bool = False
        self.loop_enabled: bool = False
        self.track: dict = {}                        # calibration track record (from ledger)
        # last_run_ms moves only on a FORECAST. In monitor mode nothing forecasts, so
        # these two are the timestamps that actually describe freshness.
        self.world_refreshed_ms: Optional[int] = None   # last completed sensing pass
        self.last_feed_ok_ms: Optional[int] = None      # last pass that returned >0 events
        self.feed_health: dict = {}                     # feed key -> FeedRun-ish dict
        self.last_run_ms: Optional[int] = None
        self.started_ms: int = now_ms()
        self._subs: set[asyncio.Queue] = set()

    # ── pub/sub ──
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=128)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, kind: str, payload: Any) -> None:
        msg = {"kind": kind, "ts": now_ms(), "payload": payload}
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                self._subs.discard(q)

    # ── mutations ──
    def set_predictions(self, preds: list[Prediction]) -> None:
        self.predictions = preds
        self.last_run_ms = now_ms()
        self.publish("predictions", [p.model_dump() for p in preds])

    def set_world(self, brief: WorldBrief) -> None:
        self.world = brief
        self.world_refreshed_ms = now_ms()
        self.publish("world", brief.model_dump())

    def set_feed_health(self, health: dict) -> None:
        """Record per-feed status. `last_feed_ok_ms` tracks REACHABILITY, not event
        count — a genuinely quiet feed that answered is a success, and treating it as
        a failure is the same error as treating a dead feed as quiet."""
        self.feed_health = health
        if any(v.get("status") in ("healthy", "empty") for v in health.values()):
            self.last_feed_ok_ms = now_ms()
        self.publish("feeds", health)

    def upsert_run(self, run: RunRecord) -> None:
        run.touch()
        self.runs[run.id] = run
        self.runs.move_to_end(run.id)
        while len(self.runs) > 50:
            self.runs.popitem(last=False)
        self.publish("run", run.model_dump())

    def set_generating(self, on: bool) -> None:
        self.generating = on
        self.publish("generating", {"generating": on})

    def set_loop(self, on: bool) -> None:
        self.loop_enabled = on
        self.publish("loop", {"enabled": on})

    def set_track(self, track: dict) -> None:
        self.track = track
        self.publish("track", track)

    # ── snapshot ──
    def snapshot(self) -> dict:
        return {
            "config": CONFIG.summary(),
            "generating": self.generating,
            "loop_enabled": self.loop_enabled,
            "last_run_ms": self.last_run_ms,
            "world_refreshed_ms": self.world_refreshed_ms,
            "last_feed_ok_ms": self.last_feed_ok_ms,
            "uptime_ms": now_ms() - self.started_ms,
            "track_record": self.track,
            "world": self.world.model_dump() if self.world else None,
            "predictions": [p.model_dump() for p in self.predictions],
            "runs": [r.model_dump() for r in list(self.runs.values())[-8:]],
        }

    @staticmethod
    def sse(msg: dict) -> str:
        return f"data: {json.dumps(msg)}\n\n"


STATE = EngineState()
