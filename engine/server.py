"""PYTHIA oracle API — Osiris world data in, future predictions out."""
from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import __version__
from .config import CONFIG
from .state import STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("pythia.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .loop import LOOP, SENSE
    from .monitor.schedule import SCHEDULER
    SENSE.start()   # cheap sensing (no LLM) — runs in BOTH modes
    if not CONFIG.research_mode:
        # The registry, written to `sources` at boot. Doing it here rather than inside
        # collect means a source is registered even if its very first fetch fails —
        # otherwise a permanently broken feed would never appear anywhere at all.
        try:
            from .monitor.collect import load_adapters_with_failures, register_sources
            modules, failures = load_adapters_with_failures()
            if failures:
                # Loud, and recorded as errored sources rather than a shrunken registry.
                log.error("%s adapter module(s) failed to import: %s", len(failures),
                          ", ".join(n for n, _ in failures))
            log.info("registered %s sources from %s module(s), %s failed",
                     register_sources(adapters=modules, import_failures=failures),
                     len(modules), len(failures))
        except Exception as e:  # noqa: BLE001 — never block startup on bookkeeping
            log.warning("source registration failed: %s", type(e).__name__)
    if CONFIG.research_mode:
        LOOP.start()
    else:
        SCHEDULER.start()   # the daily brief — monitor mode's only LLM call
    log.info("PYTHIA up in %s mode | %s", CONFIG.mode, CONFIG.summary())

    async def _boot():
        from .pipeline import run_prediction
        if not CONFIG.research_mode:
            # Monitor mode needs no boot pass: SenseLoop's first iteration collects
            # immediately. Doing it here as well fired every adapter TWICE within a
            # second of startup — pointless load on eight public APIs, and enough to
            # trip a rate limit on the ones that have one.
            return
        from . import ledger
        from .runtime import intake
        # seed the track record from disk so restarts show history immediately
        try:
            STATE.track = ledger.track_record()
        except Exception as e:  # noqa: BLE001
            log.warning("track record seed failed: %s", e)
        # wait for Osiris to be reachable, then give its routes a moment to compile
        for _ in range(20):
            if await intake.health():
                break
            await asyncio.sleep(2)
        await asyncio.sleep(4)
        # run_prediction senses the world itself — no separate refresh_world (double-fetch)
        await run_prediction(trigger="boot")

    boot = asyncio.create_task(_boot(), name="pythia-boot")
    try:
        yield
    finally:
        # explicit shutdown — background tasks were previously left dangling
        boot.cancel()
        await LOOP.stop()
        await SENSE.stop()
        await SCHEDULER.stop()
        for t in (boot,):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


app = FastAPI(title="PYTHIA Monitor", version=__version__, lifespan=lifespan)
# Explicit origins only. An empty list means no cross-origin browser access at all,
# which is correct for a loopback/private-network service.
if CONFIG.cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=CONFIG.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

# Routes reachable without a bearer token — liveness/readiness probes only, so a
# container orchestrator never needs the secret.
_OPEN_PATHS = {"/healthz", "/readyz"}


@app.middleware("http")
async def _require_token(request, call_next):
    """Bearer-token gate. Inactive when PYTHIA_API_TOKEN is blank (loopback default)."""
    if CONFIG.api_token and request.url.path not in _OPEN_PATHS:
        sent = (request.headers.get("authorization") or "")
        expected = f"Bearer {CONFIG.api_token}"
        if not secrets.compare_digest(sent, expected):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


def _research_only() -> None:
    """Refuse forecast routes unless research mode is explicitly on."""
    if not CONFIG.research_mode:
        raise HTTPException(409, "forecasting is retired; set PYTHIA_MODE=research to enable it")


_DASHBOARD = Path(__file__).parent / "dashboard.html"


@app.get("/healthz")
async def healthz():
    """Liveness: the process is up. No dependencies checked."""
    return {"status": "ok", "mode": CONFIG.mode, "version": __version__}


@app.get("/readyz")
async def readyz():
    """Readiness: at least one feed has actually DELIVERED.

    A completed sensing pass is not enough — when every feed is down the pass
    still completes and publishes an empty brief. Requiring a successful feed is
    what keeps 'quiet world' and 'all 23 feeds broken' from looking identical."""
    if CONFIG.research_mode:
        health = STATE.feed_health
    else:
        from .monitor.collect import health_from_persisted_runs
        from .monitor.store import get_store
        health = health_from_persisted_runs(get_store())
    healthy = [k for k, v in health.items() if v.get("status") in ("healthy", "empty")]
    failing = [k for k, v in health.items()
               if v.get("status") in ("error", "import_error")]
    stale = [k for k, v in health.items()
             if v.get("status") in ("stale", "never_run")]
    # READINESS RULE (decided for defect D1b): ready means at least one source is
    # delivering RIGHT NOW. If every source is stale or has never run, the service is
    # NOT ready — even though each of those sources succeeded at some point, which is
    # precisely the state that used to report 13/13 healthy while nothing collected.
    # `last_feed_ok_ms` alone could not express this: it never goes back down.
    ready = bool(healthy) if not CONFIG.research_mode else STATE.last_feed_ok_ms is not None
    return JSONResponse(
        {"ready": ready, "mode": CONFIG.mode,
         "world_refreshed_at": STATE.world_refreshed_ms,
         "last_successful_feed_at": STATE.last_feed_ok_ms,
         # Monitor mode holds no in-memory events; its unit of work is the observation.
         "event_count": (len(STATE.events) if CONFIG.research_mode else STATE.observation_count),
         "feeds_ok": len(healthy), "feeds_failing": len(failing),
         "feeds_stale": len(stale),
         "failing": sorted(failing)[:10], "stale": sorted(stale)[:10]},
        status_code=200 if ready else 503,
    )


@app.get("/feeds/health")
async def feeds_health():
    """Per-feed status, so a stale or broken source is visible instead of silent.

    In monitor mode this is served from the PERSISTED feed_runs table, so a restart no
    longer wipes it. `source_count` is the registry as recorded in `sources`, and it is
    reported next to `feed_count`: a source that is registered but has never produced a
    run is the signature of a silently skipped adapter, and the two numbers differing is
    the only way to see it."""
    if CONFIG.research_mode:
        fh = STATE.feed_health
        counts: dict = {}
        for v in fh.values():
            counts[v.get("status", "unknown")] = counts.get(v.get("status", "unknown"), 0) + 1
        return {"checked_at": STATE.world_refreshed_ms, "feed_count": len(fh),
                "source_count": len(fh), "counts": counts, "feeds": fh}

    from .monitor.collect import (
        discovered_adapter_count,
        health_counts,
        health_from_persisted_runs,
    )
    from .monitor.store import get_store
    store = get_store()
    fh = health_from_persisted_runs(store)
    counts = health_counts(fh)
    # Three populations, deliberately reported side by side. They agreeing is the
    # normal case; any disagreement names a specific failure that used to be silent:
    # modules on disk that never reached the registry, or registered sources this
    # process has not collected (defect D1).
    return {"checked_at": STATE.world_refreshed_ms,
            "feed_count": len(fh),
            "source_count": store.count_sources(),
            "adapter_module_count": discovered_adapter_count(),
            "counts": counts, "feeds": fh}


@app.get("/sources")
async def sources():
    """What this monitor is watching, as recorded at boot from the adapter registry."""
    from .monitor.store import get_store
    rows = get_store().list_sources()
    return {"count": len(rows), "sources": rows}


@app.get("/stories")
async def stories(beat: "str | None" = None, limit: int = 50):
    """Stories, newest change first. Read-only; same token rules as every other route."""
    from .monitor.store import get_store
    limit = max(1, min(int(limit), 500))
    rows = get_store().list_stories(beat=beat, limit=limit)
    return {"count": len(rows), "beat": beat, "limit": limit, "stories": rows}


@app.get("/story/{story_id}")
async def story(story_id: str):
    """One story: its metadata, the observations linked to it, and their revisions —
    which for a market instrument IS the price history."""
    from .monitor.store import get_store
    row = get_store().get_story(story_id)
    if not row:
        raise HTTPException(404, "no such story")
    return row


@app.get("/brief/latest")
async def brief_latest():
    """The newest brief a reader should see. A `failed` run is never returned here —
    that is exactly the point: a dead provider leaves yesterday's brief in place."""
    from .monitor.schedule import SCHEDULER
    from .monitor.store import get_store
    row = get_store().latest_brief()
    if not row:
        raise HTTPException(404, "no brief has been published yet")
    return {"brief": row, "next_fire": SCHEDULER.next_fire_iso,
            "last_run": SCHEDULER.last_result}


@app.post("/brief/run")
async def brief_run():
    """Collect and build a brief NOW. Mutating, so the bearer-token gate covers it."""
    from .monitor.schedule import run_once
    result = await run_once()
    return result


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """A self-contained live view of the swarm (SSE-driven). No build step."""
    return _DASHBOARD.read_text()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "pythia-oracle", "config": CONFIG.summary()}


@app.get("/config")
async def config():
    return CONFIG.summary()


_links_cache: dict = {"ts": 0.0, "data": None}


@app.get("/links")
async def links():
    import time as _t
    now = _t.monotonic()
    if _links_cache["data"] and now - _links_cache["ts"] < 8:
        data = dict(_links_cache["data"])
    else:
        from .runtime import intake, oracle
        osiris_up, oracle_up = await asyncio.gather(intake.health(), oracle.health())
        data = {"engine": True, "osiris": bool(osiris_up), "oracle": bool(oracle_up)}
        _links_cache.update(ts=now, data=dict(data))
    from .runtime import oracle as _oracle
    data.update(model=_oracle.model, generating=STATE.generating,
                loop=STATE.loop_enabled, last_run_ms=STATE.last_run_ms,
                prediction_count=len(STATE.predictions))
    return data


@app.get("/models")
async def models():
    """Installed local models + the one currently in use."""
    from .runtime import oracle
    return {"models": await oracle.list_models(), "current": oracle.model}


@app.post("/model")
async def set_model(payload: dict = Body(...)):
    """Switch the DRAFT oracle's model at runtime. Swarm personas keep their boot-time models."""
    from .runtime import oracle
    name = (payload or {}).get("model", "").strip()
    if not name:
        raise HTTPException(400, "provide `model`")
    oracle.model = name
    STATE.publish("model", {"model": name})
    log.info("oracle model switched -> %s", name)
    return {"model": oracle.model, "swarm_models": CONFIG.swarm_models}


@app.get("/predictions")
async def predictions(horizon: str | None = None, min_probability: float = 0.0):
    """Current forecasts, optionally filtered by `horizon` (24h|week|month|year)
    and `min_probability` (0..1)."""
    preds = [p for p in STATE.predictions
             if (not horizon or p.horizon == horizon) and p.probability >= min_probability]
    return {"predictions": [p.model_dump() for p in preds],
            "horizons": CONFIG.horizons,
            "world": STATE.world.model_dump() if STATE.world else None}


@app.post("/predict")
async def predict():
    """Run an oracle pass now (sense the world -> forecast). RESEARCH MODE ONLY."""
    _research_only()
    from .pipeline import run_prediction, _lock
    if STATE.generating or _lock.locked():
        return {"status": "already running"}
    # claim synchronously before yielding, so two rapid POSTs can't both start a pass
    STATE.set_generating(True)
    asyncio.create_task(run_prediction(trigger="manual"))
    return {"status": "started"}


@app.get("/agent/view")
async def agent_view():
    """One consolidated, machine-readable view of the world for external agents:
    the assembled brief, every live event (with coords), and current predictions.
    For a live feed, subscribe to GET /state/stream (SSE)."""
    from .runtime import oracle
    by_domain: dict[str, list] = {}
    for e in STATE.events:
        by_domain.setdefault(e.category, []).append({
            "title": e.title, "summary": e.summary, "source": e.source,
            "lat": e.lat, "lng": e.lng, "salience": e.salience, "ts": e.ts,
        })
    return {
        "mode": CONFIG.mode,
        # last_run_ms only moves when a FORECAST runs, so it is stale in monitor mode.
        # These three describe the sensing loop, which is what actually refreshes this view.
        "world_refreshed_at": STATE.world_refreshed_ms,
        "last_successful_feed_at": STATE.last_feed_ok_ms,
        "forecast_generated_at": (STATE.last_run_ms if CONFIG.research_mode else None),
        "generated_at": STATE.world_refreshed_ms,   # back-compat alias, now sensing-based
        "model": oracle.model,
        "summary": (STATE.world.text if STATE.world else ""),
        "domains": (STATE.world.domains if STATE.world else {}),
        "events_by_domain": by_domain,
        "event_count": len(STATE.events),
        "predictions": ([p.model_dump() for p in STATE.predictions] if CONFIG.research_mode else []),
        "live_stream": "/state/stream",
    }


@app.get("/agent/events")
async def agent_events(domain: str | None = None, source: str | None = None,
                       min_salience: float = 0.0, since: int = 0, limit: int = 0):
    """Every live world event, with optional filters so an agent gets exactly what it wants:
    `domain` (category), `source`, `min_salience` (0..1), `since` (epoch ms), `limit`.
    Returned most-salient first, with the list of available domains for discovery."""
    out = []
    for e in STATE.events:
        if domain and e.category != domain:
            continue
        if source and e.source != source:
            continue
        if e.salience < min_salience:
            continue
        if since and e.ts < since:
            continue
        out.append(e)
    out.sort(key=lambda e: e.salience, reverse=True)
    if limit > 0:
        out = out[:limit]
    return {"count": len(out), "events": [e.model_dump() for e in out],
            "domains_available": sorted({e.category for e in STATE.events})}


@app.get("/world")
async def world():
    if not STATE.world:
        raise HTTPException(404, "no world brief yet — run /predict")
    return STATE.world.model_dump()


@app.post("/resolve")
async def resolve():
    """Run a resolution sweep now (judge expired forecasts against the current brief).
    RESEARCH MODE ONLY."""
    _research_only()
    from . import ledger
    from .models import now_ms
    from .resolver import resolve_due
    n = await resolve_due(limit=20)
    return {"judged": n, "pending": len(ledger.due_for_resolution(now_ms(), limit=999))}


@app.get("/history")
async def history(horizon: str | None = None, status: str | None = None, limit: int = 200):
    """Every persisted forecast joined with its resolution (disk-backed, survives restarts).
    `status` ∈ pending|resolved_true|resolved_false|unresolvable. RESEARCH MODE ONLY."""
    _research_only()
    from . import ledger
    return {"history": ledger.history(horizon, status, limit),
            "track_record": ledger.track_record()}


@app.get("/runs")
async def runs():
    return {"runs": [r.model_dump() for r in list(STATE.runs.values())[-20:]]}


@app.get("/state")
async def state():
    return STATE.snapshot()


@app.get("/state/stream")
async def stream():
    async def gen():
        q = STATE.subscribe()
        try:
            yield STATE.sse({"kind": "snapshot", "payload": STATE.snapshot()})
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield STATE.sse(msg)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            STATE.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/chat")
async def chat(payload: dict = Body(...)):
    """Ask the oracle anything — it sees every live source + current predictions."""
    from .runtime import intake, oracle
    from .world_state import build_brief
    msg = (payload or {}).get("message", "").strip()
    if not msg:
        raise HTTPException(400, "provide `message`")
    brief = STATE.world
    if brief is None:
        try:
            brief = build_brief(await intake.fetch(limit=150))
            STATE.set_world(brief)
        except Exception:  # noqa: BLE001
            brief = None
    answer = await oracle.chat(msg, brief, STATE.predictions, payload.get("history", []))
    return {"answer": answer}


@app.post("/loop")
async def loop(payload: dict = Body(default={})):
    _research_only()
    STATE.set_loop(bool(payload.get("enabled", not STATE.loop_enabled)))
    return {"loop_enabled": STATE.loop_enabled}
