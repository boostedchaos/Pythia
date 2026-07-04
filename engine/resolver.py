"""The resolution judge — scores expired forecasts against today's world.

When a prediction's horizon closes, an LLM judge reads the current world brief and
decides whether the predicted event actually happened. Verdicts (including
`unresolvable`) are terminal and land in the ledger, which turns them into Brier
scores. One batched call per sweep; zero LLM cost when nothing is due.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .config import CONFIG
from .models import now_ms
from .state import STATE
from . import ledger

log = logging.getLogger("pythia.resolver")

_SYSTEM = (
    "You are PYTHIA's resolution judge. You will see forecasts whose time windows have "
    "now CLOSED, plus a live snapshot of the world today. For each forecast, decide "
    "whether the predicted event actually HAPPENED within its window. Judge only what "
    "the statement literally claims — no credit for near-misses or partial outcomes. "
    "If the snapshot and your general knowledge are insufficient to tell either way, "
    'answer "unresolvable" — never guess. Output strictly JSON.'
)


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _prompt(brief_text: str, due: list[dict]) -> str:
    listing = "\n".join(
        f"{i}. [window: {_utc(p['ts'])} -> {_utc(p['expires_ms'])}] \"{p['statement']}\""
        for i, p in enumerate(due))
    return (
        f"=== TODAY'S WORLD SNAPSHOT (evidence) ===\n{brief_text[:5000]}\n\n"
        f"=== EXPIRED FORECASTS ===\n{listing}\n\n"
        f"For EACH forecast return one object:\n"
        f'{{"i": <index>, "outcome": "true" | "false" | "unresolvable", '
        f'"confidence": <0-100, how sure you are of this verdict>, '
        f'"rationale": "<one sentence citing the evidence, or its absence>"}}\n'
        f"Return ONLY a JSON array — no markdown, no commentary."
    )


async def resolve_due(limit: int = 10) -> int:
    """Judge expired, unresolved predictions against the current world brief.
    Returns the number judged. Makes NO LLM call when nothing is due."""
    due = ledger.due_for_resolution(now_ms(), limit=limit)
    if not due:
        return 0
    brief = STATE.world
    if brief is None or not brief.text:
        log.info("resolver: %d due but no world brief yet — skipping sweep", len(due))
        return 0

    from .oracle import Oracle
    judge = Oracle(model=CONFIG.judge_model)   # own client: /model switches never touch the judge
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _prompt(brief.text, due)}]
    try:
        text = await judge._complete(messages, max_tokens=3000)
    except Exception as e:  # noqa: BLE001 — a failed sweep just retries next interval
        log.warning("resolver: judge call failed: %s", e)
        return 0

    judged = 0
    for chunk in Oracle._extract_objects(text):
        try:
            o = json.loads(chunk)
            i = int(o["i"])
            outcome = str(o.get("outcome", "")).strip().lower()
        except (ValueError, TypeError, KeyError):
            continue
        if not 0 <= i < len(due) or outcome not in ("true", "false", "unresolvable"):
            continue
        try:
            conf = max(0.0, min(1.0, float(o.get("confidence", 50)) / 100.0))
        except (TypeError, ValueError):
            conf = 0.5
        ledger.append_resolution(
            prediction_id=due[i]["id"], outcome=outcome, confidence=round(conf, 2),
            rationale=str(o.get("rationale", "")).strip()[:400],
            judge_model=judge.model, brief_id=brief.id)
        judged += 1
    # anything the judge skipped stays pending for the next sweep
    log.info("resolver: judged %d/%d due forecasts with %s", judged, len(due), judge.model)
    if judged:
        STATE.set_track(ledger.track_record())
    return judged
