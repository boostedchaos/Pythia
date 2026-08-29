"""The oracle pass: sense the world (Osiris) -> think (LLM) -> predictions."""
from __future__ import annotations

import asyncio
import logging

from .models import RunRecord
from .state import STATE
from .world_state import build_brief

log = logging.getLogger("pythia.pipeline")

# one oracle pass at a time (the local model is single-stream)
_lock = asyncio.Lock()


async def refresh_world() -> int:
    """Cheap sensing pass — refresh live events + brief WITHOUT calling the LLM.
    Keeps the agent view and oracle context current between forecasts."""
    from .runtime import intake
    try:
        events, health = await intake.fetch_with_health(limit=250)
        STATE.events = events
        STATE.set_feed_health(health)
        STATE.set_world(build_brief(events))
        return len(events)
    except Exception as e:  # noqa: BLE001
        log.warning("sense refresh failed: %s", e)
        return 0


async def refresh_monitor() -> int:
    """Monitor-mode sensing: run the direct feed adapters and persist what changed.

    This REPLACES the Osiris intake in monitor mode (plan Phase 0.5). Research mode
    keeps `refresh_world` untouched, so the archived experiment still reproduces."""
    from .monitor.collect import collect_once, health_from_runs
    try:
        runs = await collect_once()
        STATE.set_feed_health(health_from_runs(runs))
        count = sum(len(r.observations) for r in runs)
        STATE.note_monitor_pass(count)
        return count
    except Exception as e:  # noqa: BLE001
        log.warning("monitor collection failed: %s", e)
        return 0


async def run_prediction(trigger: str = "manual") -> RunRecord:
    """RESEARCH MODE ONLY. Forecasting is retired — see PYTHIA-MONITOR-V1-PLAN.md.
    Guarded here as well as at every caller so no future caller can re-enable it by accident."""
    from .config import CONFIG
    if not CONFIG.research_mode:
        raise RuntimeError("run_prediction called in monitor mode — forecasting is retired")

    from .runtime import intake, oracle

    run = RunRecord(trigger=trigger, stage="queued")
    STATE.upsert_run(run)

    async def stage(name: str, info: str = "") -> None:
        run.touch(name)
        if info:
            log.info("[%s] %s: %s", run.id, name, info)
        STATE.upsert_run(run)

    async with _lock:
        STATE.set_generating(True)
        try:
            await stage("sensing", "reading Osiris feeds")
            # high cap so no single source (weather alerts, news) starves the others;
            # build_brief then takes the top few per domain.
            events = await intake.fetch(limit=250)
            STATE.events = events
            brief = build_brief(events)
            run.brief = brief
            STATE.set_world(brief)
            await stage("thinking", f"{brief.event_count} signals -> oracle")

            preds = await oracle.predict(brief, on_stage=stage)

            # swarm deliberation: a council of personas re-weighs each forecast
            from .config import CONFIG
            if CONFIG.swarm_enabled and preds:
                from .swarm import deliberate
                from .runtime import PERSONA_CLIENTS
                try:
                    preds = await deliberate(PERSONA_CLIENTS, brief, preds, on_stage=stage, fallback=oracle)
                except Exception as e:  # noqa: BLE001 — never let the swarm sink a run
                    log.warning("swarm deliberation skipped: %s", e)

            STATE.set_predictions(preds)
            run.prediction_ids = [p.id for p in preds]
            try:
                from . import ledger
                ledger.append_predictions(run.id, preds, brief, oracle.model)
            except Exception as e:  # noqa: BLE001 — a disk hiccup never sinks a pass
                log.warning("ledger persist failed: %s", e)
            await stage("done", f"{len(preds)} predictions")
        except Exception as e:  # noqa: BLE001
            run.error = str(e)
            await stage("error", str(e))
            log.exception("oracle pass failed")
        finally:
            STATE.set_generating(False)
    return run
