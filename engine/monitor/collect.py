"""Run every registered adapter, persist what came back, report health.

One `httpx.AsyncClient` is shared across adapters (connection reuse, one timeout
policy). An adapter that raises anyway is converted to `status="error"` here, so a
single bad module can never zero out the whole collection pass.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import httpx

from ..config import HTTPX_VERIFY
from .models import SNAPSHOT, STREAM, AdapterRun
from .store import Store, get_store, now_ms, obs_id_for

log = logging.getLogger("pythia.monitor.collect")

_TIMEOUT_SEC = 30


# Source ids that have actually been COLLECTED since this process started. A row in
# `sources` with no entry here is a registered adapter this process has never run —
# which is exactly the shape of a silent skip, and is invisible if you only look at
# persisted runs (defect D1b).
_SEEN_THIS_PROCESS: "set[str]" = set()


def seen_this_process() -> "set[str]":
    return set(_SEEN_THIS_PROCESS)


def reset_seen_this_process() -> None:
    """Tests only — the process-lifetime marker is global by nature."""
    _SEEN_THIS_PROCESS.clear()


def load_adapters_with_failures() -> "tuple[list, list[tuple[str, str]]]":
    """`(modules, [(module_name, error), ...])`.

    The failures are RETURNED, not swallowed. Before defect D1a they were a single
    WARNING and the registry silently shrank from thirteen modules to zero, which
    /feeds/health then rendered as thirteen healthy sources."""
    try:
        from .adapters import ADAPTERS, IMPORT_FAILURES
        return list(ADAPTERS), list(IMPORT_FAILURES)
    except Exception as e:  # noqa: BLE001 — the package itself is unusable
        log.error("adapter registry unavailable: %s: %s", type(e).__name__, e)
        return [], [("<registry>", f"{type(e).__name__}: {e}"[:200])]


def discovered_adapter_count() -> int:
    """Adapter MODULE FILES on disk, counted without importing any of them. Compared
    against `sources` and against the health feed count, this is what makes a registry
    that shrank visible: the files are still there even when the imports failed."""
    try:
        from .adapters import discover_module_names
        return len(discover_module_names())
    except Exception:  # noqa: BLE001
        return 0


def _load_adapters() -> list:
    """Imported lazily so the spine's tests can install fakes and so an import error
    in one lane's package never stops the engine booting."""
    return load_adapters_with_failures()[0]


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.split("@")[-1].split(":")[0].strip().lower()
    except Exception:  # noqa: BLE001
        return ""
    return host[4:] if host.startswith("www.") else host


def source_meta(module, sample_url: str = "") -> dict:
    """What the `sources` table records about one adapter.

    DISPLAY_NAME and CANONICAL_DOMAIN are Phase 1 additions, so a module that only
    meets the 0.5 contract must still register rather than crash the registry — a new
    adapter arriving without them is a missing label, never a dead monitor. The
    fallbacks are honest ones: the source_id itself, and the domain parsed from a real
    URL the adapter produced (or its own URL constant)."""
    source_id = getattr(module, "SOURCE_ID", getattr(module, "__name__", "unknown"))
    domain = (getattr(module, "CANONICAL_DOMAIN", "") or "").strip()
    if not domain:
        domain = _domain_of(sample_url) or _domain_of(str(getattr(module, "URL", "") or ""))
    return {
        "source_id": source_id,
        "display_name": (getattr(module, "DISPLAY_NAME", "") or "").strip() or source_id,
        "beat": getattr(module, "BEAT", "") or "",
        "kind": getattr(module, "KIND", "") or STREAM,
        "canonical_domain": domain,
        "terms_note": (getattr(module, "TERMS_NOTE", "") or "").strip(),
    }


def register_sources(store: "Store | None" = None, adapters: "list | None" = None,
                     import_failures: "list | None" = None, run_ms: "int | None" = None) -> int:
    """Upsert every registered adapter into `sources`. Returns the row count AFTER the
    upsert — the caller can compare it with the registry length, which is what makes a
    silently skipped adapter visible instead of invisible.

    A module that FAILED to import is registered too, and given an errored feed_run, so
    it appears in /feeds/health by module name instead of vanishing from the count
    (defect D1a). A source that is missing entirely is the one failure mode health
    cannot describe."""
    store = store or get_store()
    if adapters is None:
        modules, discovered_failures = load_adapters_with_failures()
    else:
        modules, discovered_failures = adapters, []
    failures = discovered_failures if import_failures is None else list(import_failures)
    run_ms = run_ms or now_ms()

    for name, error in failures:
        try:
            store.upsert_source(source_id=name, display_name=f"{name} (failed to import)",
                                beat="", kind=STREAM, canonical_domain="", enabled=False,
                                terms_note="module did not import")
            store.record_feed_run(source_id=name, started_ms=run_ms, completed_ms=run_ms,
                                  status="import_error", error=error)
        except Exception as e:  # noqa: BLE001
            log.warning("could not record import failure for %s: %s", name, type(e).__name__)

    for i, module in enumerate(modules):
        try:
            store.upsert_source(**source_meta(module))
        except Exception as e:  # noqa: BLE001 — one bad module never blocks the rest
            # The module is NOT touched again here. A half-imported module can raise on
            # attribute access, and reading SOURCE_ID to name it in the log re-raised
            # inside the handler — turning the guard into the crash it was meant to
            # prevent. `__name__` is read defensively for the same reason.
            name = getattr(type(module), "__name__", "?")
            log.warning("could not register adapter #%s (%s): %s", i, name, type(e).__name__)
    # `sources` is populated now, so any observation still without a story can be
    # linked — including one whose adapter has since been retired (defect D3).
    try:
        store.link_unlinked_observations(default_kind=STREAM)
    except Exception as e:  # noqa: BLE001 — a repair pass never blocks startup
        log.warning("story backfill failed: %s", type(e).__name__)
    return store.count_sources()


async def _timed_fetch(module, client: httpx.AsyncClient) -> tuple:
    """`(run, started_ms, completed_ms)` — the timings a feed_runs row needs."""
    started = now_ms()
    run = await _safe_fetch(module, client)
    return run, started, now_ms()


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


# Statuses that mean "this source delivered". Everything else is a problem, and
# `stale` / `never_run` / `import_error` are problems that used to render as healthy.
DELIVERED = ("healthy", "empty")


def health_from_persisted_runs(store: "Store | None" = None, now_ms_: "int | None" = None,
                               stale_after_ms: "int | None" = None) -> dict:
    """/feeds/health over the LATEST PERSISTED run per source, with STALENESS applied.

    Two failures used to render as green (defect D1b). A source whose adapter stopped
    running kept serving its last good run as "latest" forever — health had
    `checked_at` in the payload but nothing ever compared it to the clock. And a source
    registered in `sources` that this process has never collected did not appear at
    all. Both now have their own status, and both are counted, so `healthy: N` cannot
    be printed while collection is not happening.

    Statuses: `healthy` / `empty` (it delivered), `error` (it ran and failed),
    `import_error` (its module would not import), `stale` (its last run is older than
    the threshold), `never_run` (registered, never collected by anyone).
    """
    from ..config import CONFIG

    store = store or get_store()
    now = now_ms_ if now_ms_ is not None else now_ms()
    horizon = stale_after_ms if stale_after_ms is not None \
        else CONFIG.feed_stale_after_sec * 1000

    latest = store.latest_feed_runs()
    registered = {r["source_id"]: r for r in store.list_sources()}
    seen_now = seen_this_process()

    out: dict = {}
    for source_id in sorted(set(latest) | set(registered)):
        row = latest.get(source_id)
        source = registered.get(source_id, {})
        entry = {
            "source": source_id,
            "path": f"adapter:{source_id}",
            "display_name": source.get("display_name") or source_id,
            "registered": source_id in registered,
            # The distinction the acceptance criterion turns on: a source can be
            # registered, have a persisted run from last week, and still not have been
            # collected once by the process answering this request.
            "ran_this_process": source_id in seen_now,
            "last_ok_at": store.last_ok_feed_run_ms(source_id),
        }
        if row is None:
            entry.update(status="never_run", error=None, http_status=None,
                         items_received=0, items_accepted=0, items_rejected=0,
                         checked_at=None, age_ms=None)
            out[source_id] = entry
            continue

        checked_at = row["completed_ms"] or row["started_ms"]
        age = None if checked_at is None else max(0, now - checked_at)
        status = row["status"]
        if status in DELIVERED and age is not None and age > horizon:
            # It last succeeded, but that was long enough ago that "healthy" would be
            # a claim about the past presented as a claim about now.
            status = "stale"
        entry.update(status=status, error=row["error"], http_status=row["http_status"],
                     items_received=row["received"], items_accepted=row["accepted"],
                     items_rejected=(row["rejected"] if "rejected" in row.keys() else 0),
                     checked_at=checked_at, age_ms=age, persisted=True)
        out[source_id] = entry
    return out


def health_counts(health: dict) -> dict:
    """Status tally plus the two populations a status alone cannot express."""
    counts: dict = {}
    for entry in health.values():
        key = entry.get("status", "unknown")
        counts[key] = counts.get(key, 0) + 1
    counts["not_run_this_process"] = sum(
        1 for e in health.values() if not e.get("ran_this_process"))
    counts["delivering"] = sum(
        1 for e in health.values() if e.get("status") in DELIVERED)
    return counts


async def collect_once(store: "Store | None" = None, adapters: "list | None" = None,
                       run_ms: "int | None" = None) -> "list[AdapterRun]":
    """Fetch every adapter, persist, and return the runs for health reporting."""
    store = store or get_store()
    modules = adapters if adapters is not None else _load_adapters()
    if not modules:
        return []
    run_ms = run_ms or now_ms()

    async with httpx.AsyncClient(verify=HTTPX_VERIFY, timeout=_TIMEOUT_SEC) as client:
        timed = await asyncio.gather(*[_timed_fetch(m, client) for m in modules])

    runs = [t[0] for t in timed]
    for module, (run, started_ms, completed_ms) in zip(modules, timed):
        kind = getattr(module, "KIND", "") or STREAM
        _SEEN_THIS_PROCESS.add(run.source_id)
        rejected = 0
        if run.observations:
            counts = store.upsert_observations(run.observations, run_ms, kind=kind)
            rejected = counts.get("rejected", 0)
            if rejected:
                # `accepted` must mean "stored". Leaving the adapter's own count here
                # would hide a malformed batch behind a healthy-looking number.
                run.accepted = max(0, (run.accepted or len(run.observations)) - rejected)
                run.rejected = rejected
        # Presence is recorded ONLY for a run that actually succeeded. Writing an
        # errored run's empty id-set would make every instrument look GONE — a feed
        # outage must read as an outage, never as world-changing news.
        if kind == SNAPSHOT and run.status != "error":
            store.record_snapshot_presence(
                run.source_id, [obs_id_for(o) for o in run.observations], run_ms)
        # Persist the run itself, ALWAYS — including the errors. A run that is not
        # written is a run that health cannot report after a restart.
        try:
            store.record_feed_run(
                source_id=run.source_id, started_ms=started_ms, completed_ms=completed_ms,
                status=run.status, http_status=run.http_status, received=run.received,
                accepted=run.accepted or len(run.observations), error=run.error,
                rejected=rejected)
        except Exception as e:  # noqa: BLE001 — health bookkeeping never sinks a pass
            log.warning("could not persist feed run for %s: %s", run.source_id,
                        type(e).__name__)
    return list(runs)
