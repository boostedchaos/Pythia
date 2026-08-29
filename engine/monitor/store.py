"""SQLite spine for PYTHIA Monitor — observations, snapshot presence, briefs, spend.

Identity is the whole point of this file (contract: docs/phase-0.5-contract.md):

    obs_id = sha256(f"{source_id}|{natural_key}")[:24]
    natural_key = upstream_id or canonical_url or normalized_title   (first non-empty)

The price of a market instrument is deliberately NOT part of identity (plan §5.11) —
it lives in `extra`, so a moving price is a CHANGE to one row, never a new row.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path

from .models import Observation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    obs_id        TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL,
    beat          TEXT NOT NULL,
    upstream_id   TEXT,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    content_hash  TEXT NOT NULL,
    extra_json    TEXT NOT NULL DEFAULT '{}',
    source_ts_ms  INTEGER,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms  INTEGER NOT NULL,
    changed_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_obs_first_seen ON observations(first_seen_ms);
CREATE INDEX IF NOT EXISTS ix_obs_changed_at ON observations(changed_at_ms);
CREATE INDEX IF NOT EXISTS ix_obs_source     ON observations(source_id);

CREATE TABLE IF NOT EXISTS snapshot_presence (
    source_id TEXT NOT NULL,
    obs_id    TEXT NOT NULL,
    run_ms    INTEGER NOT NULL,
    PRIMARY KEY (source_id, obs_id, run_ms)
);
CREATE INDEX IF NOT EXISTS ix_pres_run ON snapshot_presence(source_id, run_ms);

CREATE TABLE IF NOT EXISTS briefs (
    brief_date        TEXT PRIMARY KEY,
    coverage_start_ms INTEGER NOT NULL,
    coverage_end_ms   INTEGER NOT NULL,
    markdown          TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL,
    model             TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cost_usd          REAL,
    created_ms        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_spend (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms    INTEGER NOT NULL,
    purpose  TEXT NOT NULL,
    model    TEXT,
    cost_usd REAL
);
CREATE INDEX IF NOT EXISTS ix_spend_ts ON llm_spend(ts_ms);
"""

# A brief in one of these states is a real brief a reader can be shown.
PUBLISHABLE = ("published", "deterministic")


def now_ms() -> int:
    return int(time.time() * 1000)


def _norm_title(title: str) -> str:
    return " ".join(title.lower().split())


def natural_key(obs: Observation) -> str:
    """First non-empty of upstream_id, url, normalized title. Contract §Identity."""
    for candidate in ((obs.upstream_id or "").strip(), (obs.url or "").strip(),
                      _norm_title(obs.title or "")):
        if candidate:
            return candidate
    return ""


def obs_id_for(obs: Observation) -> str:
    raw = f"{obs.source_id}|{natural_key(obs)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def content_hash_for(obs: Observation) -> str:
    """Hash of the MUTABLE content: title, summary, and every extra attribute.

    A market price lives in `extra`, so a price move changes this hash (-> CHANGED)
    while `obs_id` is untouched (-> not NEW). That split is the whole design."""
    extra = json.dumps(obs.extra or {}, sort_keys=True, default=str)
    return hashlib.sha256(f"{obs.title}|{obs.summary}|{extra}".encode("utf-8")).hexdigest()


def default_db_path() -> Path:
    """`PYTHIA_DATA_DIR`/monitor.db, matching config.py's data_dir handling."""
    root = Path(__file__).resolve().parent.parent.parent
    data_dir = Path(os.environ.get("PYTHIA_DATA_DIR", str(root / "runs")))
    return data_dir / "monitor.db"


class Store:
    """One connection, WAL, every run wrapped in a single transaction."""

    def __init__(self, path: "Path | str | None" = None) -> None:
        self.path = Path(path) if path is not None else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ── observations ──

    def upsert_observations(self, observations: "list[Observation]", run_ms: int) -> dict:
        """Insert/update a whole adapter run atomically. Returns {new, changed, seen}.

        Same record twice -> one row and the SAME obs_id; `first_seen_ms` is never
        rewritten, so an unchanged story cannot re-enter tomorrow's NEW list."""
        counts = {"new": 0, "changed": 0, "seen": 0}
        with self._lock:
            cur = self.conn.cursor()
            try:
                for obs in observations:
                    oid = obs_id_for(obs)
                    chash = content_hash_for(obs)
                    row = cur.execute(
                        "SELECT content_hash FROM observations WHERE obs_id=?", (oid,)).fetchone()
                    extra_json = json.dumps(obs.extra or {}, sort_keys=True, default=str)
                    if row is None:
                        cur.execute(
                            "INSERT INTO observations (obs_id, source_id, beat, upstream_id, url,"
                            " title, summary, content_hash, extra_json, source_ts_ms,"
                            " first_seen_ms, last_seen_ms, changed_at_ms)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (oid, obs.source_id, obs.beat, obs.upstream_id, obs.url, obs.title,
                             obs.summary or "", chash, extra_json, obs.source_ts_ms,
                             run_ms, run_ms, run_ms))
                        counts["new"] += 1
                    elif row["content_hash"] != chash:
                        cur.execute(
                            "UPDATE observations SET title=?, summary=?, url=?, beat=?,"
                            " content_hash=?, extra_json=?, source_ts_ms=?, last_seen_ms=?,"
                            " changed_at_ms=? WHERE obs_id=?",
                            (obs.title, obs.summary or "", obs.url, obs.beat, chash, extra_json,
                             obs.source_ts_ms, run_ms, run_ms, oid))
                        counts["changed"] += 1
                    else:
                        cur.execute("UPDATE observations SET last_seen_ms=? WHERE obs_id=?",
                                    (run_ms, oid))
                    counts["seen"] += 1
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return counts

    def get(self, obs_id: str) -> "dict | None":
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM observations WHERE obs_id=?", (obs_id,)).fetchone()
        return dict(row) if row else None

    def get_many(self, obs_ids: "list[str]") -> dict:
        """obs_id -> row dict, for the renderer's URL lookup."""
        if not obs_ids:
            return {}
        out = {}
        with self._lock:
            for i in range(0, len(obs_ids), 400):
                chunk = obs_ids[i:i + 400]
                q = "SELECT * FROM observations WHERE obs_id IN (%s)" % ",".join("?" * len(chunk))
                for row in self.conn.execute(q, chunk):
                    out[row["obs_id"]] = dict(row)
        return out

    def count_observations(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) c FROM observations").fetchone()["c"])

    # ── snapshot presence ──

    def record_snapshot_presence(self, source_id: str, obs_ids: "list[str]", run_ms: int) -> None:
        """The full id-set a snapshot source reported in THIS run.

        Only ever called for a run that actually succeeded — recording an errored
        run's (empty) id-set would render every instrument as GONE."""
        with self._lock:
            try:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO snapshot_presence (source_id, obs_id, run_ms)"
                    " VALUES (?,?,?)", [(source_id, o, run_ms) for o in obs_ids])
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def snapshot_sources(self) -> "list[str]":
        with self._lock:
            return [r["source_id"] for r in self.conn.execute(
                "SELECT DISTINCT source_id FROM snapshot_presence")]

    def snapshot_runs(self, source_id: str, at_or_before_ms: "int | None" = None,
                      limit: int = 2) -> "list[int]":
        """The most recent run timestamps for a snapshot source, newest first."""
        q = "SELECT DISTINCT run_ms FROM snapshot_presence WHERE source_id=?"
        args: list = [source_id]
        if at_or_before_ms is not None:
            q += " AND run_ms<=?"
            args.append(at_or_before_ms)
        q += " ORDER BY run_ms DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [r["run_ms"] for r in self.conn.execute(q, args)]

    def snapshot_ids(self, source_id: str, run_ms: int) -> "set[str]":
        with self._lock:
            return {r["obs_id"] for r in self.conn.execute(
                "SELECT obs_id FROM snapshot_presence WHERE source_id=? AND run_ms=?",
                (source_id, run_ms))}

    # ── briefs ──

    def save_brief(self, brief_date: str, coverage_start_ms: int, coverage_end_ms: int,
                   markdown: str, status: str, model: "str | None" = None,
                   prompt_tokens: "int | None" = None, completion_tokens: "int | None" = None,
                   cost_usd: "float | None" = None, created_ms: "int | None" = None) -> None:
        """Write a brief row.

        A `failed` row never overwrites a real brief for the same date: a provider
        outage must leave yesterday's (or this morning's) brief exactly as it was."""
        with self._lock:
            try:
                if status not in PUBLISHABLE:
                    existing = self.conn.execute(
                        "SELECT status FROM briefs WHERE brief_date=?", (brief_date,)).fetchone()
                    if existing and existing["status"] in PUBLISHABLE:
                        self.conn.commit()
                        return
                self.conn.execute(
                    "INSERT OR REPLACE INTO briefs (brief_date, coverage_start_ms,"
                    " coverage_end_ms, markdown, status, model, prompt_tokens,"
                    " completion_tokens, cost_usd, created_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (brief_date, coverage_start_ms, coverage_end_ms, markdown, status, model,
                     prompt_tokens, completion_tokens, cost_usd, created_ms or now_ms()))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def latest_brief(self) -> "dict | None":
        """The newest brief a reader should see — never a failed one."""
        placeholders = ",".join("?" * len(PUBLISHABLE))
        with self._lock:
            row = self.conn.execute(
                f"SELECT * FROM briefs WHERE status IN ({placeholders})"
                " ORDER BY coverage_end_ms DESC, brief_date DESC LIMIT 1",
                list(PUBLISHABLE)).fetchone()
        return dict(row) if row else None

    def get_brief(self, brief_date: str) -> "dict | None":
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM briefs WHERE brief_date=?", (brief_date,)).fetchone()
        return dict(row) if row else None

    # ── spend ──

    def record_spend(self, purpose: str, model: "str | None", cost_usd: "float | None",
                     ts_ms: "int | None" = None) -> None:
        """`cost_usd=None` is recorded as NULL — an unknown cost is never estimated."""
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO llm_spend (ts_ms, purpose, model, cost_usd) VALUES (?,?,?,?)",
                    (ts_ms or now_ms(), purpose, model, cost_usd))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def spend_since(self, start_ms: int) -> float:
        """Summed KNOWN cost since `start_ms`. NULL rows contribute 0 — they are
        unknown, not free, so `spend_unknown_rows` reports them alongside."""
        with self._lock:
            row = self.conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0.0) s FROM llm_spend WHERE ts_ms>=?",
                (start_ms,)).fetchone()
        return float(row["s"])

    def spend_unknown_rows(self, start_ms: int) -> int:
        with self._lock:
            return int(self.conn.execute(
                "SELECT COUNT(*) c FROM llm_spend WHERE ts_ms>=? AND cost_usd IS NULL",
                (start_ms,)).fetchone()["c"])


_STORE: "Store | None" = None
_STORE_LOCK = threading.Lock()


def get_store() -> Store:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = Store()
        return _STORE


def set_store(store: "Store | None") -> None:
    """Point the process at a different database (tests, or a re-configured data dir)."""
    global _STORE
    with _STORE_LOCK:
        _STORE = store


def observation_dict(obs: Observation) -> dict:
    d = asdict(obs)
    d["obs_id"] = obs_id_for(obs)
    return d
