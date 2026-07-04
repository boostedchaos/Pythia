"""Self-check for the calibration ledger — pure, no network, no LLM.

Run:  uv run python -m engine.test_ledger
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .config import CONFIG
from .models import AgentView, Prediction, WorldBrief
from .oracle import Oracle


def _fresh_ledger(tmp: str):
    from . import ledger
    CONFIG.runs_dir = Path(tmp)
    ledger.reset_cache_for_tests()
    return ledger


def _pred(pid: str, horizon: str, prob: float, base: float | None = None,
          agents: list | None = None, ts: int = 1_000_000) -> Prediction:
    return Prediction(id=pid, statement=f"event {pid}", horizon=horizon, probability=prob,
                      base_probability=base, agents=agents or [], ts=ts)


def test_expiry_and_roundtrip(tmp: str) -> None:
    ledger = _fresh_ledger(tmp)
    brief = WorldBrief(top_events=[f"t{i}" for i in range(20)])
    preds = [_pred("a", "24h", 0.6), _pred("b", "week", 0.3)]
    ledger.append_predictions("run_1", preds, brief, "test-model")

    ledger.reset_cache_for_tests()   # force reload from disk
    hist = ledger.history()
    assert len(hist) == 2, hist
    a = next(h for h in hist if h["id"] == "a")
    assert a["expires_ms"] == 1_000_000 + ledger.HORIZON_MS["24h"]
    assert a["status"] == "pending" and a["brief_top"] == [f"t{i}" for i in range(12)]
    print("ok — expiry math + jsonl round-trip survives a reload")


def test_due_and_resolution(tmp: str) -> None:
    ledger = _fresh_ledger(tmp)
    brief = WorldBrief()
    ledger.append_predictions("run_1", [_pred("a", "24h", 0.6), _pred("b", "year", 0.3)], brief, "m")
    now = 1_000_000 + ledger.HORIZON_MS["24h"] + 1
    due = ledger.due_for_resolution(now)
    assert [d["id"] for d in due] == ["a"], due          # b's year horizon not yet expired
    ledger.append_resolution("a", "true", 0.9, "it happened", "judge-m", "brief_x")
    assert ledger.due_for_resolution(now) == []          # resolved -> no longer due
    assert ledger.history(status="resolved_true")[0]["id"] == "a"
    print("ok — due_for_resolution excludes unexpired + resolved")


def test_brier(tmp: str) -> None:
    ledger = _fresh_ledger(tmp)
    votes = [AgentView(name="Skeptic", probability=0.2), AgentView(name="Strategist", probability=0.9)]
    ledger.append_predictions("run_1", [
        _pred("a", "24h", 0.8, base=0.6, agents=votes),   # -> true
        _pred("b", "24h", 0.4, base=0.5, agents=votes),   # -> false
        _pred("c", "week", 0.7),                          # -> unresolvable
    ], WorldBrief(), "m")
    ledger.append_resolution("a", "true", 0.9, "", "j", None)
    ledger.append_resolution("b", "false", 0.8, "", "j", None)
    ledger.append_resolution("c", "unresolvable", 0.3, "", "j", None)
    t = ledger.track_record()
    # hand-computed: ((0.8-1)^2 + (0.4-0)^2)/2 = (0.04+0.16)/2 = 0.1
    assert t["brier"] == 0.1, t
    # base: ((0.6-1)^2 + (0.5-0)^2)/2 = (0.16+0.25)/2 = 0.205
    assert t["brier_base"] == 0.205, t
    assert t["resolved"] == 2 and t["unresolvable"] == 1 and t["pending"] == 0
    # Skeptic: ((0.2-1)^2 + (0.2-0)^2)/2 = (0.64+0.04)/2 = 0.34
    assert t["by_persona"]["Skeptic"]["brier"] == 0.34, t
    assert t["by_horizon"]["24h"]["n"] == 2
    print("ok — Brier arithmetic (overall, base, per-persona, per-horizon)")


def test_judge_output_parse() -> None:
    noisy = ('Here are my verdicts:\n```json\n'
             '[{"i": 0, "outcome": "true", "confidence": 85, "rationale": "seen in brief"},\n'
             ' {"i": 1, "outcome": "unresolvable", "confidence": 30, "rationale": "no evidence"}]\n'
             '```\nHope that helps!')
    objs = Oracle._extract_objects(noisy)
    assert len(objs) == 2, objs
    import json
    assert json.loads(objs[0])["outcome"] == "true"
    print("ok — judge output parses through fences + prose")


def main() -> None:
    for fn in (test_expiry_and_roundtrip, test_due_and_resolution, test_brier):
        with tempfile.TemporaryDirectory() as tmp:
            fn(tmp)
    test_judge_output_parse()
    print("ok — ledger verified (4 checks passed)")


if __name__ == "__main__":
    main()
