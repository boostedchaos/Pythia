"""Deterministic change detection. No LLM reaches this file — by construction.

NEW      first seen inside the window
CHANGED  content changed inside the window, but first seen BEFORE it
GONE     snapshot sources only: present in the previous full id-set, absent from the latest
"""
from __future__ import annotations

from .store import Store


def _rows(store: Store, sql: str, args: "list") -> "list[dict]":
    with store._lock:  # noqa: SLF001 — same module family; one connection, one lock
        return [dict(r) for r in store.conn.execute(sql, args)]


def compute(store: Store, window_start_ms: int, window_end_ms: int) -> dict:
    """Half-open window (start, end]. Adjacent windows therefore never double-count:
    yesterday's `coverage_end_ms` is tomorrow's `window_start_ms`."""
    new = _rows(store,
                "SELECT * FROM observations WHERE first_seen_ms>? AND first_seen_ms<=?"
                " ORDER BY first_seen_ms DESC", [window_start_ms, window_end_ms])
    changed = _rows(store,
                    "SELECT * FROM observations WHERE changed_at_ms>? AND changed_at_ms<=?"
                    " AND first_seen_ms<=? ORDER BY changed_at_ms DESC",
                    [window_start_ms, window_end_ms, window_start_ms])

    gone: list[dict] = []
    for source_id in store.snapshot_sources():
        runs = store.snapshot_runs(source_id, at_or_before_ms=window_end_ms, limit=2)
        if len(runs) < 2:
            continue  # one run is not a comparison; nothing can be shown to have gone
        latest_ids = store.snapshot_ids(source_id, runs[0])
        previous_ids = store.snapshot_ids(source_id, runs[1])
        missing = sorted(previous_ids - latest_ids)
        if missing:
            rows = store.get_many(missing)
            gone.extend(rows[o] for o in missing if o in rows)

    return {"new": new, "changed": changed, "gone": gone}
