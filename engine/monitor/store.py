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
import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path

from .models import BEATS, SNAPSHOT, STREAM, Observation

log = logging.getLogger("pythia.monitor.store")

_SCHEMA_V1 = """
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

# Schema v2 (docs/phase-1-contract.md). Every statement is IF NOT EXISTS, so applying
# it to a v1 database ADDS tables and touches no existing row — that is what makes the
# migration lossless rather than a copy-and-swap.
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL,
    beat             TEXT NOT NULL,
    kind             TEXT NOT NULL,
    canonical_domain TEXT NOT NULL DEFAULT '',
    enabled          INTEGER NOT NULL DEFAULT 1,
    terms_note       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS feed_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL,
    started_ms   INTEGER NOT NULL,
    completed_ms INTEGER,
    status       TEXT NOT NULL,
    http_status  INTEGER,
    received     INTEGER NOT NULL DEFAULT 0,
    accepted     INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS ix_feed_runs_source ON feed_runs(source_id, completed_ms DESC);

CREATE TABLE IF NOT EXISTS revisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    obs_id       TEXT NOT NULL,
    ts_ms        INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    changed_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_revisions_obs ON revisions(obs_id, ts_ms);

CREATE TABLE IF NOT EXISTS stories (
    story_id        TEXT PRIMARY KEY,
    story_key       TEXT NOT NULL UNIQUE,
    beat            TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    first_seen_ms   INTEGER NOT NULL,
    last_changed_ms INTEGER NOT NULL,
    obs_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_stories_beat ON stories(beat, last_changed_ms DESC);

CREATE TABLE IF NOT EXISTS story_observations (
    story_id TEXT NOT NULL,
    obs_id   TEXT NOT NULL,
    PRIMARY KEY (story_id, obs_id)
);
CREATE INDEX IF NOT EXISTS ix_story_obs_obs ON story_observations(obs_id);
"""

# Schema v3 adds one column. `ALTER TABLE ... ADD COLUMN` is not IF NOT EXISTS in
# SQLite, so this step is applied only when the stored version is below 3.
_MIGRATIONS_V3 = (
    "ALTER TABLE feed_runs ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0",
)

SCHEMA_VERSION = 3

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


def story_key_for(obs: Observation, kind: str, obs_id: "str | None" = None) -> str:
    """Deterministic story identity — no similarity scoring in v1 (contract, deliberate).

    A `snapshot` source reports the full current state each fetch, so one upstream id
    (a symbol, a CVE, a country) is ONE story across all time and its level history
    lives in `revisions`. That is the §5.11 fix: a moving price must not manufacture a
    new story any more than it manufactures a new observation. A `stream` source has no
    such stable subject, so a story is 1:1 with the observation until Phase 2 clustering.
    """
    if kind == SNAPSHOT and (obs.upstream_id or "").strip():
        return f"{obs.source_id}|{obs.upstream_id.strip()}"
    # The STORED obs_id, never a recomputed one. They are the same for anything this
    # process wrote, but a row migrated from v1 can carry an id computed under an older
    # rule — and the story of an observation must key on the id the link table uses.
    return obs_id or obs_id_for(obs)


def story_id_for(story_key: str) -> str:
    return hashlib.sha256(story_key.encode("utf-8")).hexdigest()[:24]


def changed_fields(before: dict, obs: Observation) -> dict:
    """{field: [old, new]} across title, summary and every `extra` key.

    Extra keys are reported individually (`extra.price`) rather than as one blob, so a
    price history is a query over one field instead of a diff of two JSON documents."""
    out: dict = {}
    if before.get("title") != obs.title:
        out["title"] = [before.get("title"), obs.title]
    if (before.get("summary") or "") != (obs.summary or ""):
        out["summary"] = [before.get("summary"), obs.summary or ""]
    try:
        old_extra = json.loads(before.get("extra_json") or "{}")
    except (TypeError, ValueError):
        old_extra = {}
    new_extra = obs.extra or {}
    for key in sorted(set(old_extra) | set(new_extra)):
        if old_extra.get(key) != new_extra.get(key):
            out[f"extra.{key}"] = [old_extra.get(key), new_extra.get(key)]
    return out


def provenance_problem(obs: Observation) -> "str | None":
    """Why this observation may not be stored, or None if it is well-formed.

    Defect D2: before this existed the invariant held only because all thirteen
    adapters each carried their own `if not url: continue`. The fourteenth that forgot
    would have written broken rows silently, and the whole-db provenance test would
    still have passed — it only ever inspected rows its own fakes produced. `NOT NULL`
    does not catch an empty string, so the check has to be here, at the boundary."""
    if not (obs.source_id or "").strip():
        return "empty source_id"
    url = (obs.url or "").strip()
    if not url:
        return "empty url"
    if not url.lower().startswith(("http://", "https://")):
        # A `javascript:` or `data:` link is not a citation a reader can follow, and
        # the brief renders these straight into a markdown link.
        return f"url scheme is not http(s): {url.split(':', 1)[0][:20]!r}"
    if obs.beat not in BEATS:
        return f"beat {obs.beat!r} is not one of BEATS"
    return None


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
            self.schema_version = self._migrate()
        # Repairs a database migrated from v1, and any row a crash left unlinked.
        # Only sources already known here — see the method's docstring.
        self.link_unlinked_observations()

    # ── schema ──

    def _migrate(self) -> int:
        """Bring whatever is on disk up to SCHEMA_VERSION, in place, without data loss.

        The version is read BEFORE any DDL runs: after `_SCHEMA_V1` executes, a fresh
        file and a populated v1 file look identical, so the pre-DDL read is the only
        moment the two can be told apart. Each step only ADDS tables and columns, so an
        existing row is never rewritten and never copied.

        **This is NOT atomic, and the guarantee it does offer is a different one**
        (defect D5). `executescript` commits any open transaction before it runs, so
        the `rollback()` below cannot undo DDL that already landed — an interrupted
        migration leaves a partially-built schema committed on disk. What makes that
        safe is not a transaction but the shape of the statements: every one is
        `IF NOT EXISTS`, and the version row is written LAST, so a half-migrated file
        reopens, re-runs the same steps over the tables it already has, and completes.
        The property is self-healing on reopen, not all-or-nothing, and
        `test_a_half_migrated_database_heals_on_reopen` is what holds it to that."""
        cur = self.conn.cursor()
        have_version_table = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
        ).fetchone() is not None
        if have_version_table:
            row = cur.execute("SELECT MAX(version) v FROM schema_version").fetchone()
            version = int(row["v"] or 0)
        else:
            # No version table: either an empty file or a v1 database written before
            # versioning existed. Both are handled by running every step from 0.
            version = 0
        try:
            self.conn.executescript(_SCHEMA_V1)
            if version < 2:
                self.conn.executescript(_SCHEMA_V2)
            if version < 3:
                have = {r["name"] for r in self.conn.execute("PRAGMA table_info(feed_runs)")}
                for stmt in _MIGRATIONS_V3:
                    # ADD COLUMN has no IF NOT EXISTS, so the self-healing property
                    # above has to be supplied by hand for this one step.
                    if "rejected" not in have:
                        self.conn.execute(stmt)
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                              "version INTEGER PRIMARY KEY, applied_ms INTEGER NOT NULL)")
            # Written LAST and only for the version actually reached. Older version
            # rows are kept: `MAX(version)` is what the next open reads.
            self.conn.execute("INSERT OR IGNORE INTO schema_version (version, applied_ms)"
                              " VALUES (?,?)", (SCHEMA_VERSION, now_ms()))
            self.conn.commit()
        except Exception:
            # Cannot undo the DDL above (see the docstring); this only discards a
            # pending row write. The reopen is what repairs a partial migration.
            self.conn.rollback()
            raise
        return SCHEMA_VERSION

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ── observations ──

    def upsert_observations(self, observations: "list[Observation]", run_ms: int,
                            kind: str = STREAM) -> dict:
        """Insert/update a whole adapter run atomically. Returns {new, changed, seen}.

        Same record twice -> one row and the SAME obs_id; `first_seen_ms` is never
        rewritten, so an unchanged story cannot re-enter tomorrow's NEW list.

        Every observation is validated first (`provenance_problem`). A malformed one is
        REJECTED and counted — `counts["rejected"]` and `counts["rejected_reasons"]` —
        rather than stored, so the provenance invariant is a property of the spine
        instead of a convention thirteen adapters happen to share (defect D2). One bad
        record never sinks the rest of its run.

        `kind` is the SOURCE's KIND, which decides story identity (see `story_key_for`).
        The story row and its link are written inside this same transaction as the
        observation, so a crash can never leave an observation with no story.

        The story link is refreshed on EVERY path — new, changed and unchanged — which
        is also how a database migrated from v1 acquires stories: the first collection
        pass after the migration links the rows that already existed, with no guess
        about a KIND that was never recorded."""
        counts: dict = {"new": 0, "changed": 0, "seen": 0, "rejected": 0,
                        "rejected_reasons": {}}
        accepted = []
        for obs in observations:
            problem = provenance_problem(obs)
            if problem is None:
                accepted.append(obs)
                continue
            counts["rejected"] += 1
            counts["rejected_reasons"][problem] = \
                counts["rejected_reasons"].get(problem, 0) + 1
        if counts["rejected"]:
            log.warning("rejected %s malformed observation(s) from %s: %s",
                        counts["rejected"],
                        (observations[0].source_id if observations else "?"),
                        counts["rejected_reasons"])

        with self._lock:
            cur = self.conn.cursor()
            try:
                for obs in accepted:
                    oid = obs_id_for(obs)
                    chash = content_hash_for(obs)
                    row = cur.execute(
                        "SELECT * FROM observations WHERE obs_id=?", (oid,)).fetchone()
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
                        # The revision is the history. Without this append a price move
                        # overwrites its predecessor and the series is gone for good.
                        cur.execute(
                            "INSERT INTO revisions (obs_id, ts_ms, content_hash, changed_json)"
                            " VALUES (?,?,?,?)",
                            (oid, run_ms, chash,
                             json.dumps(changed_fields(dict(row), obs), sort_keys=True,
                                        default=str)))
                        counts["changed"] += 1
                    else:
                        cur.execute("UPDATE observations SET last_seen_ms=? WHERE obs_id=?",
                                    (run_ms, oid))
                    self._link_story(cur, obs, oid, kind, run_ms,
                                     changed=row is None or row["content_hash"] != chash)
                    counts["seen"] += 1
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return counts

    def _link_story(self, cur, obs: Observation, oid: str, kind: str, run_ms: int,
                    changed: bool) -> None:
        """Create-or-update the story for one observation. Caller holds the lock and
        owns the transaction — this never commits."""
        skey = story_key_for(obs, kind, oid)
        sid = story_id_for(skey)
        existing = cur.execute("SELECT * FROM stories WHERE story_id=?", (sid,)).fetchone()
        if existing is None:
            cur.execute(
                "INSERT INTO stories (story_id, story_key, beat, source_id, title,"
                " first_seen_ms, last_changed_ms, obs_count) VALUES (?,?,?,?,?,?,?,0)",
                (sid, skey, obs.beat, obs.source_id, obs.title, run_ms, run_ms))
        elif changed:
            # The title tracks the newest observation so a story reads as its current
            # state; first_seen_ms is never rewritten (same rule as the observation).
            cur.execute("UPDATE stories SET title=?, last_changed_ms=? WHERE story_id=?",
                        (obs.title, run_ms, sid))
        cur.execute("INSERT OR IGNORE INTO story_observations (story_id, obs_id) VALUES (?,?)",
                    (sid, oid))
        cur.execute(
            "UPDATE stories SET obs_count=(SELECT COUNT(*) FROM story_observations"
            " WHERE story_id=?) WHERE story_id=?", (sid, sid))

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
                        # Nothing was written, so there is nothing to commit. The
                        # commit() that used to sit here would end an unrelated
                        # transaction another method had opened on this shared
                        # connection (defect D6, minor).
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


    def link_unlinked_observations(self, default_kind: "str | None" = None) -> int:
        """Give a story to every observation that has none. Returns the count linked.

        Defect D3: a v1 database is migrated without stories (migration cannot know a
        source's KIND, which v1 never recorded), and the design relied on "the next
        collection pass links them". That only reaches rows the feed still reports. On
        the deployed box 58 rows — 50 gdelt, 8 state_dept_advisories — had aged out of
        their feeds before the upgrade, so they were never re-seen, never linked, and
        unreachable from /stories. The claim that a crash can never leave an
        observation without a story was true of crashes and false of migration.

        `default_kind=None` links only observations whose source is KNOWN in `sources`,
        which is the right thing at store-open time: the registry has not been written
        yet, and guessing `stream` for a snapshot source would mint a wrong 1:1 story
        that the real pass could then never correct. Boot calls it again with
        `default_kind=STREAM` once `sources` is populated, to sweep up rows whose
        adapter has since been retired."""
        with self._lock:
            kinds = {r["source_id"]: r["kind"] for r in self.conn.execute(
                "SELECT source_id, kind FROM sources")}
            orphans = [dict(r) for r in self.conn.execute(
                "SELECT o.* FROM observations o LEFT JOIN story_observations so"
                " ON so.obs_id = o.obs_id WHERE so.obs_id IS NULL")]
            if not orphans:
                return 0
            cur = self.conn.cursor()
            linked = 0
            try:
                for row in orphans:
                    kind = kinds.get(row["source_id"], default_kind)
                    if kind is None:
                        continue  # unknown source, and no fallback allowed yet
                    try:
                        extra = json.loads(row["extra_json"] or "{}")
                    except (TypeError, ValueError):
                        extra = {}
                    obs = Observation(
                        source_id=row["source_id"], title=row["title"], url=row["url"],
                        beat=row["beat"], summary=row["summary"] or "",
                        upstream_id=row["upstream_id"], source_ts_ms=row["source_ts_ms"],
                        extra=extra)
                    # first_seen is preserved: the story is as old as its observation,
                    # not as old as the repair that noticed it was missing.
                    self._link_story(cur, obs, row["obs_id"], kind,
                                     row["first_seen_ms"], changed=False)
                    linked += 1
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        if linked:
            log.info("linked %s observation(s) that had no story", linked)
        return linked

    def count_unlinked_observations(self) -> int:
        with self._lock:
            return int(self.conn.execute(
                "SELECT COUNT(*) c FROM observations o LEFT JOIN story_observations so"
                " ON so.obs_id = o.obs_id WHERE so.obs_id IS NULL").fetchone()["c"])

    # ── sources ──

    def upsert_source(self, source_id: str, display_name: str, beat: str, kind: str,
                      canonical_domain: str = "", enabled: bool = True,
                      terms_note: str = "") -> None:
        """Register one adapter. Called at boot for every module in the registry, so
        `sources` is the answer to 'what is this monitor actually watching'."""
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO sources (source_id, display_name, beat, kind,"
                    " canonical_domain, enabled, terms_note) VALUES (?,?,?,?,?,?,?)"
                    " ON CONFLICT(source_id) DO UPDATE SET display_name=excluded.display_name,"
                    " beat=excluded.beat, kind=excluded.kind,"
                    " canonical_domain=excluded.canonical_domain, enabled=excluded.enabled,"
                    " terms_note=excluded.terms_note",
                    (source_id, display_name, beat, kind, canonical_domain,
                     1 if enabled else 0, terms_note))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def list_sources(self) -> "list[dict]":
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM sources ORDER BY beat, source_id")]

    def count_sources(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"])

    # ── feed runs ──

    def record_feed_run(self, source_id: str, started_ms: int, completed_ms: "int | None",
                        status: str, http_status: "int | None" = None, received: int = 0,
                        accepted: int = 0, error: "str | None" = None,
                        rejected: int = 0) -> int:
        with self._lock:
            try:
                cur = self.conn.execute(
                    "INSERT INTO feed_runs (source_id, started_ms, completed_ms, status,"
                    " http_status, received, accepted, error, rejected)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (source_id, started_ms, completed_ms, status, http_status,
                     received, accepted, error, rejected))
                self.conn.commit()
                return int(cur.lastrowid)
            except Exception:
                self.conn.rollback()
                raise

    def latest_feed_runs(self) -> "dict[str, dict]":
        """source_id -> its most recent run. This is what makes /feeds/health survive a
        restart: health used to live only in memory, so a fresh process reported nothing
        at all — indistinguishable from every feed being down."""
        out: dict = {}
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM feed_runs WHERE id IN"
                " (SELECT MAX(id) FROM feed_runs GROUP BY source_id)")
            for row in rows:
                out[row["source_id"]] = dict(row)
        return out

    def last_ok_feed_run_ms(self, source_id: str) -> "int | None":
        with self._lock:
            row = self.conn.execute(
                "SELECT MAX(completed_ms) m FROM feed_runs WHERE source_id=?"
                " AND status IN ('healthy','empty')", (source_id,)).fetchone()
        return row["m"] if row and row["m"] is not None else None

    # ── revisions ──

    def revisions(self, obs_id: str, limit: int = 200) -> "list[dict]":
        with self._lock:
            return [dict(r) for r in self.conn.execute(
                "SELECT * FROM revisions WHERE obs_id=? ORDER BY ts_ms, id LIMIT ?",
                (obs_id, limit))]

    def count_revisions(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) c FROM revisions").fetchone()["c"])

    # ── stories ──

    def list_stories(self, beat: "str | None" = None, limit: int = 50) -> "list[dict]":
        q = "SELECT * FROM stories"
        args: list = []
        if beat:
            q += " WHERE beat=?"
            args.append(beat)
        q += " ORDER BY last_changed_ms DESC, story_id LIMIT ?"
        args.append(limit)
        with self._lock:
            return [dict(r) for r in self.conn.execute(q, args)]

    def get_story(self, story_id: str) -> "dict | None":
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stories WHERE story_id=?", (story_id,)).fetchone()
            if row is None:
                return None
            story = dict(row)
            story["obs_ids"] = [r["obs_id"] for r in self.conn.execute(
                "SELECT obs_id FROM story_observations WHERE story_id=? ORDER BY obs_id",
                (story_id,))]
            revs = [dict(r) for r in self.conn.execute(
                "SELECT rv.* FROM revisions rv JOIN story_observations so"
                " ON so.obs_id = rv.obs_id WHERE so.story_id=?"
                " ORDER BY rv.ts_ms, rv.id", (story_id,))]
        for rev in revs:
            try:
                rev["changed"] = json.loads(rev.get("changed_json") or "{}")
            except (TypeError, ValueError):
                rev["changed"] = {}
        story["revisions"] = revs
        return story

    def count_stories(self) -> int:
        with self._lock:
            return int(self.conn.execute("SELECT COUNT(*) c FROM stories").fetchone()["c"])

    # ── retention ──

    def prune(self, cutoff_ms: int) -> dict:
        """Delete everything older than `cutoff_ms`, in ONE transaction.

        An observation is aged on `last_seen_ms`, not `first_seen_ms`: a KEV entry first
        seen two years ago and still being republished today is current, and pruning it
        on its birthday would make it reappear tomorrow as NEW.

        Briefs are KEPT — they are the product, and they are small. A story goes only
        when its last observation goes, so a long-running story survives the loss of its
        oldest observations."""
        counts = {"observations": 0, "revisions": 0, "feed_runs": 0,
                  "snapshot_presence": 0, "story_observations": 0, "stories": 0,
                  "llm_spend": 0}
        with self._lock:
            cur = self.conn.cursor()
            try:
                doomed = [r["obs_id"] for r in cur.execute(
                    "SELECT obs_id FROM observations WHERE last_seen_ms < ?", (cutoff_ms,))]
                for i in range(0, len(doomed), 400):
                    chunk = doomed[i:i + 400]
                    marks = ",".join("?" * len(chunk))
                    counts["revisions"] += cur.execute(
                        f"DELETE FROM revisions WHERE obs_id IN ({marks})", chunk).rowcount
                    counts["story_observations"] += cur.execute(
                        f"DELETE FROM story_observations WHERE obs_id IN ({marks})",
                        chunk).rowcount
                    counts["snapshot_presence"] += cur.execute(
                        f"DELETE FROM snapshot_presence WHERE obs_id IN ({marks})",
                        chunk).rowcount
                    counts["observations"] += cur.execute(
                        f"DELETE FROM observations WHERE obs_id IN ({marks})", chunk).rowcount
                counts["snapshot_presence"] += cur.execute(
                    "DELETE FROM snapshot_presence WHERE run_ms < ?", (cutoff_ms,)).rowcount
                counts["feed_runs"] += cur.execute(
                    "DELETE FROM feed_runs WHERE COALESCE(completed_ms, started_ms) < ?",
                    (cutoff_ms,)).rowcount
                # Spend rows age out too. The monthly cap only ever reads the last
                # month, so a year-old row is dead weight; briefs stay because they are
                # the product. (Not in the contract, which lists neither table.)
                counts["llm_spend"] += cur.execute(
                    "DELETE FROM llm_spend WHERE ts_ms < ?", (cutoff_ms,)).rowcount
                counts["stories"] += cur.execute(
                    "DELETE FROM stories WHERE story_id NOT IN"
                    " (SELECT story_id FROM story_observations)").rowcount
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return counts


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
