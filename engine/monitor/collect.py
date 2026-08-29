"""Run every registered adapter, persist what came back, report health.

One `httpx.AsyncClient` is shared across adapters (connection reuse, one timeout
policy). An adapter that raises anyway is converted to `status="error"` here, so a
single bad module can never zero out the whole collection pass.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from ..config import HTTPX_VERIFY
from .models import SNAPSHOT, AdapterRun
from .store import Store, get_store, now_ms, obs_id_for

log = logging.getLogger("pythia.monitor.collect")

_TIMEOUT_SEC = 30


def _load_adapters() -> list:
    """Imported lazily so the spine's tests can install fakes and so an import error
    in one lane's package never stops the engine booting."""
    try:
        from .adapters import ADAPTERS
        return list(ADAPTERS)
    except Exception as e:  # noqa: BLE001
        log.warning("adapter registry unavailable: %s", e)
        return []


async def _safe_fetch(module, client: httpx.AsyncClient) -> AdapterRun:
    source_id = getattr(module, "SOURCE_ID", getattr(module, "__name__", "unknown"))
    try:
        run = await module.fetch(client)
        if not isinstance(run, AdapterRun):
            raise TypeError(f"fetch() returned {type(run).__name__}, expected AdapterRun")
        return run
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 — the contract says fetch never raises; enforce it
        return AdapterRun(source_id=source_id, status="error", observations=[],
                          error=f"{type(e).__name__}: {e}"[:200])


def health_from_runs(runs: "list[AdapterRun]") -> dict:
    """Same shape the Osiris intake publishes, so /feeds/health needs no new schema."""
    out: dict = {}
    for run in runs:
        out[run.source_id] = {
            "source": run.source_id,
            "path": f"adapter:{run.source_id}",
            "status": run.status,
            "error": run.error,
            "http_status": run.http_status,
            "items_received": run.received,
            "items_accepted": run.accepted or len(run.observations),
            "last_ok_at": now_ms() if run.status in ("healthy", "empty") else None,
        }
    return out


async def collect_once(store: "Store | None" = None, adapters: "list | None" = None,
                       run_ms: "int | None" = None) -> "list[AdapterRun]":
    """Fetch every adapter, persist, and return the runs for health reporting."""
    store = store or get_store()
    modules = adapters if adapters is not None else _load_adapters()
    if not modules:
        return []
    run_ms = run_ms or now_ms()

    async with httpx.AsyncClient(verify=HTTPX_VERIFY, timeout=_TIMEOUT_SEC) as client:
        runs = await asyncio.gather(*[_safe_fetch(m, client) for m in modules])

    for module, run in zip(modules, runs):
        if run.observations:
            store.upsert_observations(run.observations, run_ms)
        # Presence is recorded ONLY for a run that actually succeeded. Writing an
        # errored run's empty id-set would make every instrument look GONE — a feed
        # outage must read as an outage, never as world-changing news.
        if getattr(module, "KIND", "") == SNAPSHOT and run.status != "error":
            store.record_snapshot_presence(
                run.source_id, [obs_id_for(o) for o in run.observations], run_ms)
    return list(runs)
