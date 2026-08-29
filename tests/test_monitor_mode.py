"""Phase 0 acceptance: monitor mode must make ZERO forecast/resolver calls.

These are the tests the plan's Phase 0 acceptance criteria ask for. They are
written to FAIL LOUDLY if forecasting is ever re-enabled by accident.
"""
from __future__ import annotations

import importlib
import os

import pytest


def _reload_config(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import engine.config as cfg
    importlib.reload(cfg)
    return cfg


# ── mode selection ──

def test_mode_defaults_to_monitor(monkeypatch):
    monkeypatch.delenv("PYTHIA_MODE", raising=False)
    cfg = _reload_config(monkeypatch)
    assert cfg.CONFIG.mode == "monitor"
    assert cfg.CONFIG.research_mode is False


def test_research_mode_is_opt_in(monkeypatch):
    cfg = _reload_config(monkeypatch, PYTHIA_MODE="research")
    assert cfg.CONFIG.research_mode is True


@pytest.mark.parametrize("bad", ["", "Monitor ", "reserch", "yes", "1", "RESEARCH_MODE"])
def test_unknown_mode_fails_closed_to_monitor(monkeypatch, bad):
    """A typo must never silently enable forecasting. 'Monitor ' normalises to monitor;
    everything unrecognised also lands on monitor."""
    cfg = _reload_config(monkeypatch, PYTHIA_MODE=bad)
    assert cfg.CONFIG.research_mode is False, f"{bad!r} enabled research mode"


# ── the pipeline refuses to run ──

@pytest.mark.asyncio
async def test_run_prediction_refuses_in_monitor_mode(monkeypatch):
    _reload_config(monkeypatch, PYTHIA_MODE="monitor")
    import engine.pipeline as pipeline
    importlib.reload(pipeline)
    with pytest.raises(RuntimeError, match="monitor mode"):
        await pipeline.run_prediction(trigger="test")


# ── security defaults ──

def test_engine_binds_loopback_by_default(monkeypatch):
    monkeypatch.delenv("ENGINE_HOST", raising=False)
    cfg = _reload_config(monkeypatch)
    assert cfg.CONFIG.engine_host == "127.0.0.1"


def test_cors_is_closed_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    cfg = _reload_config(monkeypatch)
    assert cfg.CONFIG.cors_origins == []


# ── readiness must distinguish "quiet" from "everything is broken" ──

def test_readyz_is_not_ready_when_every_feed_failed():
    from engine.state import EngineState
    st = EngineState()
    st.set_feed_health({f"src{i}": {"status": "error", "error": "boom"} for i in range(23)})
    assert st.last_feed_ok_ms is None, "all-feeds-down must not count as a successful fetch"


def test_readyz_is_ready_when_a_feed_answered_but_had_nothing():
    from engine.state import EngineState
    st = EngineState()
    st.set_feed_health({"usgs": {"status": "empty", "error": None},
                        "news": {"status": "error", "error": "HTTP 503"}})
    assert st.last_feed_ok_ms is not None, "a reachable-but-quiet feed IS a success"
