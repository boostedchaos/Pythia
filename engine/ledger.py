"""The ledger — every forecast persisted to disk, joined with its eventual verdict.

Append-only jsonl under CONFIG.runs_dir. Memory is only a cache of the files, so a
restart loses nothing: the track record is rebuilt from disk on first use.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from .config import CONFIG
from .models import Prediction, WorldBrief, now_ms

log = logging.getLogger("pythia.ledger")

# horizon -> its duration in ms; expiry is computed here, once, at persist time
HORIZON_MS = {
    "24h": 86_400_000,
    "week": 7 * 86_400_000,
    "month": 30 * 86_400_000,
    "year": 365 * 86_400_000,
}

_PREDICTIONS = CONFIG.runs_dir / "predictions.jsonl"
_RESOLUTIONS = CONFIG.runs_dir / "resolutions.jsonl"

# id -> record caches (loaded lazily from disk, appended in step with the files)
_preds: dict[str, dict] | None = None
_res: dict[str, dict] | None = None
_io = threading.Lock()   # ponytail: one process, rare writes; a global lock is plenty


def _load() -> tuple[dict, dict]:
    global _preds, _res
    if _preds is None:
        _preds, _res = {}, {}
        for path, cache, key in ((_PREDICTIONS, _preds, "id"), (_RESOLUTIONS, _res, "prediction_id")):
            if path.exists():
                for line in path.read_text().splitlines():
                    try:
                        rec = json.loads(line)
                        cache[rec[key]] = rec
                    except (ValueError, KeyError):
                        continue
        log.info("ledger loaded: %d predictions, %d resolutions", len(_preds), len(_res))
    return _preds, _res


def _append(path, records: list[dict]) -> None:
    with _io, path.open("a") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


_WORD = re.compile(r"[a-z0-9]+")
_DUP_JACCARD = 0.6   # word-overlap at/above this = the same running story


def _words(s: str) -> set:
    return set(_WORD.findall((s or "").lower()))


def _dupes_active(statement: str, horizon: str, now: int, cache: dict) -> bool:
    """True if a still-active (non-expired) same-horizon forecast with a very similar
    statement is already logged — so the same running story re-emitted every pass is
    persisted once, not 100×, keeping the track record from being dominated by it.
    ponytail: naive word-Jaccard over active entries, not embeddings — upgrade only if
    rewordings start slipping through."""
    words = _words(statement)
    if not words:
        return False
    for rec in cache.values():
        if rec.get("horizon") != horizon or rec.get("expires_ms", 0) <= now:
            continue
        other = _words(rec.get("statement", ""))
        union = words | other
        if union and len(words & other) / len(union) >= _DUP_JACCARD:
            return True
    return False


def append_predictions(run_id: str, preds: list[Prediction], brief: WorldBrief, model: str) -> None:
    """Persist a completed pass. Called once per run; never raises past the caller's guard.
    Near-duplicates of a still-active forecast are skipped (they stay on the live deck but
    aren't re-logged) so one running story isn't counted dozens of times in the ledger."""
    cache, _ = _load()
    now = now_ms()
    records, skipped = [], 0
    for p in preds:
        if _dupes_active(p.statement, p.horizon, now, cache):
            skipped += 1
            continue
        rec = {
            "id": p.id, "run_id": run_id, "ts": p.ts,
            "expires_ms": p.ts + HORIZON_MS.get(p.horizon, HORIZON_MS["week"]),
            "statement": p.statement, "horizon": p.horizon,
            "probability": p.probability, "base_probability": p.base_probability,
            "split": p.split,
            "agents": [a.model_dump() for a in p.agents],
            "reasoning": p.reasoning, "location": p.location,
            "lat": p.lat, "lng": p.lng,
            "brief_id": p.brief_id, "brief_top": brief.top_events[:12],
            "model": model,
        }
        cache[p.id] = rec
        records.append(rec)
    _append(_PREDICTIONS, records)
    log.info("ledger: persisted %d predictions from %s (%d dupes skipped)", len(records), run_id, skipped)


def append_resolution(prediction_id: str, outcome: str, confidence: float,
                      rationale: str, judge_model: str, brief_id: str | None) -> None:
    _, cache = _load()
    rec = {"prediction_id": prediction_id, "ts": now_ms(), "outcome": outcome,
           "confidence": confidence, "rationale": rationale,
           "judge_model": judge_model, "brief_id": brief_id}
    cache[prediction_id] = rec
    _append(_RESOLUTIONS, [rec])


def due_for_resolution(now: int, limit: int = 10) -> list[dict]:
    """Expired predictions with no verdict yet, oldest expiry first."""
    preds, res = _load()
    due = [p for p in preds.values() if p["expires_ms"] <= now and p["id"] not in res]
    due.sort(key=lambda p: p["expires_ms"])
    return due[:limit]


def _status(pid: str, res: dict) -> str:
    r = res.get(pid)
    if not r:
        return "pending"
    return {"true": "resolved_true", "false": "resolved_false"}.get(r["outcome"], "unresolvable")


def history(horizon: str | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
    """All persisted predictions joined with their resolution, newest first."""
    preds, res = _load()
    out = []
    for p in sorted(preds.values(), key=lambda p: -p["ts"]):
        if horizon and p["horizon"] != horizon:
            continue
        st = _status(p["id"], res)
        if status and st != status:
            continue
        out.append({**p, "status": st, "resolution": res.get(p["id"])})
        if len(out) >= limit:
            break
    return out


def track_record() -> dict:
    """Brier scores over resolved true/false forecasts — overall, vs the pre-swarm
    draft, per horizon, and per persona (which lab model is actually calibrated)."""
    preds, res = _load()
    resolved = [(p, res[p["id"]]) for p in preds.values()
                if p["id"] in res and res[p["id"]]["outcome"] in ("true", "false")]
    unresolvable = sum(1 for r in res.values() if r["outcome"] not in ("true", "false"))

    def brier(pairs: list[tuple[float, int]]) -> float | None:
        return round(sum((p - o) ** 2 for p, o in pairs) / len(pairs), 3) if pairs else None

    overall, base, by_h, by_persona = [], [], {}, {}
    for p, r in resolved:
        o = 1 if r["outcome"] == "true" else 0
        overall.append((p["probability"], o))
        if p.get("base_probability") is not None:
            base.append((p["base_probability"], o))
        by_h.setdefault(p["horizon"], []).append((p["probability"], o))
        for a in p.get("agents") or []:
            by_persona.setdefault(a["name"], []).append((a["probability"], o))

    # the honest benchmark: what a trivial "always predict the observed base rate" scores.
    # If consensus Brier isn't well under this, the swarm has no real skill — it just looks
    # good next to the wildly overconfident raw draft (brier_base).
    outcomes = [o for _, o in overall]
    base_rate = round(sum(outcomes) / len(outcomes), 3) if outcomes else None
    brier_baserate = brier([(base_rate, o) for o in outcomes]) if base_rate is not None else None

    return {
        "resolved": len(resolved),
        "pending": len(preds) - len(res),
        "unresolvable": unresolvable,
        "brier": brier(overall),
        "brier_base": brier(base),
        "brier_baserate": brier_baserate,   # trivial always-base-rate benchmark
        "base_rate": base_rate,             # observed fraction of resolved that came true
        "by_horizon": {h: {"n": len(v), "brier": brier(v)} for h, v in by_h.items()},
        # current_model is TODAY's config; per-persona Brier pools every historical vote, which
        # may predate a model change — so the model label is not what generated all these votes.
        "by_persona": {n: {"n": len(v), "brier": brier(v),
                           "current_model": CONFIG.swarm_models.get(n, "")}
                       for n, v in by_persona.items()},
    }


def reset_cache_for_tests() -> None:
    """Drop the in-memory cache so tests can repoint CONFIG.runs_dir."""
    global _preds, _res, _PREDICTIONS, _RESOLUTIONS
    _preds = _res = None
    _PREDICTIONS = CONFIG.runs_dir / "predictions.jsonl"
    _RESOLUTIONS = CONFIG.runs_dir / "resolutions.jsonl"
