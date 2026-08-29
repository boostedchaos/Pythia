"""Phase 1: schema v2, persisted health, revisions, stories, retention.

Each test guards one clause of docs/phase-1-contract.md, and each was proven to FAIL
with the guarded behaviour reverted — the canaries are listed in the lane report.
No network: adapters are fakes defined here, and every assertion reads state back out
of SQLite rather than trusting the return value of the write that produced it.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import types
from datetime import datetime, timezone

import pytest

from engine.monitor.collect import (
    collect_once,
    health_counts,
    health_from_persisted_runs,
    register_sources,
    source_meta,
)
from engine.monitor.models import BEATS, SNAPSHOT, STREAM, AdapterRun, Observation
from engine.monitor.schedule import prune_once
from engine.monitor.store import (
    SCHEMA_VERSION,
    Store,
    changed_fields,
    obs_id_for,
    story_id_for,
    story_key_for,
)

DAY = 24 * 60 * 60 * 1000
T0 = 1_756_000_000_000


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "monitor.db")
    yield s
    s.close()


def obs(**kw) -> Observation:
    base = dict(source_id="fake_ai", title="A thing happened", url="https://example.test/1",
                beat="ai", summary="details")
    base.update(kw)
    return Observation(**base)


def price_obs(symbol: str, price: float) -> Observation:
    """A market instrument: identity is the SYMBOL, the price lives only in `extra`."""
    return Observation(source_id="fake_mkt", title=f"{symbol} spot", beat="markets",
                       url=f"https://example.test/{symbol}", upstream_id=symbol,
                       extra={"price": price, "currency": "usd"})


def fake_adapter(source_id: str, beat: str, kind: str, observations, status="healthy",
                 error=None, http_status=200, **attrs):
    async def fetch(client):
        return AdapterRun(source_id=source_id, status=status, observations=list(observations),
                          error=error, http_status=http_status,
                          received=len(observations), accepted=len(observations))
    ns = types.SimpleNamespace(SOURCE_ID=source_id, BEAT=beat, KIND=kind, fetch=fetch,
                               __name__=f"fake.{source_id}")
    for k, v in attrs.items():
        setattr(ns, k, v)
    return ns


# ── schema v2 migration ────────────────────────────────────────────────────────

# The v1 schema exactly as Phase 0.5 shipped it, frozen here as a literal. Importing
# the live `_SCHEMA_V1` would make this test follow the code it is supposed to be
# testing against — a v1 database written last month cannot change when store.py does.
_V1_SQL = """
CREATE TABLE observations (
    obs_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, beat TEXT NOT NULL,
    upstream_id TEXT, url TEXT NOT NULL, title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL,
    extra_json TEXT NOT NULL DEFAULT '{}', source_ts_ms INTEGER,
    first_seen_ms INTEGER NOT NULL, last_seen_ms INTEGER NOT NULL,
    changed_at_ms INTEGER NOT NULL);
CREATE TABLE snapshot_presence (
    source_id TEXT NOT NULL, obs_id TEXT NOT NULL, run_ms INTEGER NOT NULL,
    PRIMARY KEY (source_id, obs_id, run_ms));
CREATE TABLE briefs (
    brief_date TEXT PRIMARY KEY, coverage_start_ms INTEGER NOT NULL,
    coverage_end_ms INTEGER NOT NULL, markdown TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER,
    cost_usd REAL, created_ms INTEGER NOT NULL);
CREATE TABLE llm_spend (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts_ms INTEGER NOT NULL, purpose TEXT NOT NULL,
    model TEXT, cost_usd REAL);
"""


def _write_v1_db(path):
    """A populated v1 database, written WITHOUT any Phase 1 code in the path."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_SQL)
    conn.execute(
        "INSERT INTO observations (obs_id, source_id, beat, upstream_id, url, title,"
        " summary, content_hash, extra_json, source_ts_ms, first_seen_ms, last_seen_ms,"
        " changed_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("legacy_obs_id_0001", "old_src", "ai", "up-1", "https://example.test/legacy",
         "Legacy row", "kept", "hash-legacy", '{"price": 1.5}', T0 - DAY,
         T0 - DAY, T0 - DAY, T0 - DAY))
    conn.execute(
        "INSERT INTO briefs (brief_date, coverage_start_ms, coverage_end_ms, markdown,"
        " status, created_ms) VALUES (?,?,?,?,?,?)",
        ("2026-08-27", T0 - DAY, T0, "# legacy brief", "published", T0))
    conn.execute("INSERT INTO snapshot_presence (source_id, obs_id, run_ms) VALUES (?,?,?)",
                 ("old_src", "legacy_obs_id_0001", T0 - DAY))
    conn.execute("INSERT INTO llm_spend (ts_ms, purpose, model, cost_usd)"
                 " VALUES (?,?,?,?)", (T0, "brief", "m", 0.01))
    conn.commit()
    conn.close()


def test_a_v1_database_migrates_in_place_with_no_data_loss(tmp_path):
    """Contract: schema v2 migrates an existing v1 monitor.db IN PLACE.

    The v1 file is written by raw sqlite3 above, so this is a real upgrade of a real
    old database, not Phase 1 code checking its own output."""
    path = tmp_path / "monitor.db"
    _write_v1_db(path)

    # Prove the fixture really is a v1 file holding data, before anything migrates it.
    raw = sqlite3.connect(str(path))
    tables_before = {r[0] for r in raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "schema_version" not in tables_before
    assert not ({"sources", "feed_runs", "revisions", "stories"} & tables_before)
    assert raw.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    raw.close()

    s = Store(path)
    try:
        assert s.schema_version == SCHEMA_VERSION == 3
        tables = {r["name"] for r in s.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sources", "feed_runs", "revisions", "stories", "story_observations",
                "schema_version"} <= tables

        # Every v1 row is still there, byte for byte.
        row = s.get("legacy_obs_id_0001")
        assert row is not None
        assert row["title"] == "Legacy row"
        assert row["first_seen_ms"] == T0 - DAY
        assert row["extra_json"] == '{"price": 1.5}'
        assert s.get_brief("2026-08-27")["markdown"] == "# legacy brief"
        assert s.snapshot_ids("old_src", T0 - DAY) == {"legacy_obs_id_0001"}
        assert s.spend_since(0) == pytest.approx(0.01)
        assert s.count_observations() == 1
    finally:
        s.close()


def test_migration_is_idempotent_and_reopening_does_not_bump_the_version(tmp_path):
    path = tmp_path / "monitor.db"
    _write_v1_db(path)
    for _ in range(3):
        s = Store(path)
        assert s.schema_version == SCHEMA_VERSION
        s.close()
    conn = sqlite3.connect(str(path))
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    # v3's ADD COLUMN has no IF NOT EXISTS; three opens must not have run it twice.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(feed_runs)")]
    assert cols.count("rejected") == 1
    conn.close()


def test_v3_survives_a_database_where_the_column_landed_but_the_version_did_not(tmp_path):
    """The half-applied v3: `ALTER TABLE ADD COLUMN` succeeded, then the process died
    before the version row was written. On reopen the step runs again, and a second
    ADD COLUMN of the same name is a hard error — so the version guard alone is not
    enough and the column has to be checked for directly."""
    path = tmp_path / "monitor.db"
    _write_v1_db(path)
    s = Store(path)
    s.close()

    conn = sqlite3.connect(str(path))
    conn.execute("DELETE FROM schema_version")            # version row lost
    conn.execute("INSERT INTO schema_version VALUES (2, 1)")  # ... leaving v2 recorded
    conn.commit()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(feed_runs)")]
    assert "rejected" in cols, "the column really did land before the crash"
    conn.close()

    s = Store(path)                                        # must not raise
    try:
        assert s.schema_version == SCHEMA_VERSION
        s.record_feed_run("x", 1, 1, "healthy", rejected=2)
        assert s.latest_feed_runs()["x"]["rejected"] == 2
    finally:
        s.close()


def test_a_migrated_v1_row_acquires_its_story_on_the_next_pass(tmp_path):
    """Migration deliberately does NOT backfill stories: a v1 database never recorded
    a source KIND, so backfilling would have to guess one. The first collection pass
    after the upgrade links the existing rows instead — no guess, no orphans."""
    path = tmp_path / "monitor.db"
    _write_v1_db(path)
    s = Store(path)
    try:
        assert s.count_stories() == 0
        o = Observation(source_id="old_src", title="Legacy row", beat="ai",
                        url="https://example.test/legacy", summary="kept",
                        upstream_id="up-1", extra={"price": 1.5})
        s.upsert_observations([o], T0, kind=SNAPSHOT)
        stories = s.list_stories()
        assert len(stories) == 1
        assert stories[0]["story_key"] == "old_src|up-1"
    finally:
        s.close()


# ── acceptance 1: identity survives a process restart ──────────────────────────

def test_identity_and_first_seen_survive_a_restart(tmp_path):
    """Acceptance 1. Two Store() instances over ONE db file is the in-process stand-in
    for a VM restart: the second knows nothing except what is on disk."""
    path = tmp_path / "monitor.db"
    o = obs()

    first = Store(path)
    first.upsert_observations([o], T0)
    oid = obs_id_for(o)
    assert first.get(oid)["first_seen_ms"] == T0
    first.close()

    second = Store(path)
    try:
        # (a) the UNCHANGED path
        counts = second.upsert_observations([o], T0 + 5 * DAY)
        row = second.get(oid)
        assert second.count_observations() == 1, "the restart must not fork the row"
        assert row["obs_id"] == oid
        assert row["first_seen_ms"] == T0, "first_seen is never rewritten"
        assert row["last_seen_ms"] == T0 + 5 * DAY
        assert counts["new"] == 0, "an old story must not re-enter the NEW list"

        # (b) the CHANGED path — the one that actually matters, and the one this test
        # was blind to (defect D4). A record whose content moved is the normal case
        # for a live feed, and rewriting first_seen there would make every edited
        # story re-enter the NEW list. Deliberately rewriting first_seen on the
        # CHANGED branch left this test passing until the re-upsert below was added.
        moved = obs(title="A thing happened, updated", summary="more details")
        counts = second.upsert_observations([moved], T0 + 9 * DAY)
        row = second.get(oid)
        assert counts["changed"] == 1 and counts["new"] == 0
        assert second.count_observations() == 1
        assert row["title"] == "A thing happened, updated", "the change did land"
        assert row["first_seen_ms"] == T0, "first_seen survives a CHANGE too"
        assert row["changed_at_ms"] == T0 + 9 * DAY
    finally:
        second.close()


# ── acceptance 2: one instrument, one story, price history in revisions ────────

def test_a_moving_price_is_one_story_whose_revisions_hold_the_history(store):
    """Acceptance 2 and the §5.11 fix. Five fetches, five different prices."""
    prices = [100.0, 101.5, 99.25, 99.25, 105.0]
    for i, p in enumerate(prices):
        store.upsert_observations([price_obs("BTC", p)], T0 + i * 60_000, kind=SNAPSHOT)

    assert store.count_observations() == 1, "a price move is a CHANGE, never a new row"
    assert store.count_stories() == 1

    sid = story_id_for("fake_mkt|BTC")
    story = store.get_story(sid)
    assert story is not None
    assert story["story_key"] == "fake_mkt|BTC"
    assert story["obs_count"] == 1
    assert story["first_seen_ms"] == T0

    # One revision per actual move: the repeated 99.25 is not a change.
    moves = [r["changed"]["extra.price"] for r in story["revisions"]]
    assert moves == [[100.0, 101.5], [101.5, 99.25], [99.25, 105.0]]
    # The series is reconstructable end to end from the revisions alone.
    series = [moves[0][0]] + [m[1] for m in moves]
    assert series == [100.0, 101.5, 99.25, 105.0]


def test_two_instruments_from_one_source_are_two_stories(store):
    store.upsert_observations([price_obs("BTC", 100.0), price_obs("ETH", 5.0)],
                              T0, kind=SNAPSHOT)
    store.upsert_observations([price_obs("BTC", 110.0), price_obs("ETH", 5.0)],
                              T0 + 60_000, kind=SNAPSHOT)
    keys = sorted(s["story_key"] for s in store.list_stories())
    assert keys == ["fake_mkt|BTC", "fake_mkt|ETH"]
    assert store.count_revisions() == 1, "only BTC moved"


def test_a_stream_source_gets_one_story_per_observation(store):
    a, b = obs(url="https://example.test/a"), obs(url="https://example.test/b")
    store.upsert_observations([a, b], T0, kind=STREAM)
    stories = store.list_stories()
    assert len(stories) == 2
    assert {s["story_key"] for s in stories} == {obs_id_for(a), obs_id_for(b)}


def test_story_key_ignores_upstream_id_for_a_stream_source():
    """The snapshot rule must not leak into streams: two arXiv papers sharing nothing
    but a source are separate stories, and cross-source clustering is Phase 2."""
    o = price_obs("BTC", 100.0)
    assert story_key_for(o, SNAPSHOT) == "fake_mkt|BTC"
    assert story_key_for(o, STREAM) == obs_id_for(o)


def test_changed_json_names_the_fields_that_moved(store):
    before = obs(title="Old title", summary="old", extra={"price": 1.0, "kept": "same"})
    after = obs(title="New title", summary="new", extra={"price": 2.0, "kept": "same"})
    store.upsert_observations([before], T0)
    store.upsert_observations([after], T0 + 1000)

    revs = store.revisions(obs_id_for(before))
    assert len(revs) == 1
    changed = json.loads(revs[0]["changed_json"])
    assert changed == {"title": ["Old title", "New title"],
                       "summary": ["old", "new"],
                       "extra.price": [1.0, 2.0]}
    assert "extra.kept" not in changed, "an unchanged field is not a change"


def test_an_unchanged_upsert_appends_no_revision(store):
    o = obs()
    store.upsert_observations([o], T0)
    store.upsert_observations([o], T0 + 1000)
    assert store.count_revisions() == 0


def test_changed_fields_handles_a_key_appearing_and_disappearing():
    row = {"title": "t", "summary": "s", "extra_json": '{"a": 1}'}
    o = obs(title="t", summary="s", extra={"b": 2})
    assert changed_fields(row, o) == {"extra.a": [1, None], "extra.b": [None, 2]}


# ── acceptance 3: provenance on every observation ──────────────────────────────

async def test_every_observation_in_the_db_has_full_provenance(store):
    """Acceptance 3, asserted over the WHOLE table rather than a sampled row, and via
    a real collection pass so nothing hand-built is doing the work."""
    await collect_once(
        store=store,
        adapters=[fake_adapter("fake_ai", "ai", STREAM, [obs(), obs(url="https://e.test/2")]),
                  fake_adapter("fake_mkt", "markets", SNAPSHOT,
                               [price_obs("BTC", 100.0), price_obs("ETH", 5.0)]),
                  fake_adapter("fake_hc", "healthcare", STREAM, [], status="error",
                               error="HTTP 500")],
        run_ms=T0)

    rows = [dict(r) for r in store.conn.execute("SELECT * FROM observations")]
    assert len(rows) == 4, "the checked-count moved — this is not a vacuous pass"
    for row in rows:
        for field in ("source_id", "url", "first_seen_ms", "last_seen_ms"):
            assert row[field] is not None, f"{field} null on {row['obs_id']}"
            assert str(row[field]).strip() != "", f"{field} blank on {row['obs_id']}"
    # Every observation is reachable from a story, and every story from a source name.
    linked = {r["obs_id"] for r in store.conn.execute("SELECT obs_id FROM story_observations")}
    assert linked == {r["obs_id"] for r in rows}


# ── acceptance 4: adding a feed moves the checked-count ────────────────────────

async def _health_payload(store):
    """Call the real route function with this store installed."""
    from engine.monitor import store as store_mod
    from engine.server import feeds_health
    previous = store_mod._STORE
    store_mod.set_store(store)
    try:
        return await feeds_health()
    finally:
        store_mod.set_store(previous)


async def test_adding_a_feed_moves_both_counted_populations(store):
    """Acceptance 4. A registry of n then n+1: BOTH the sources table and the
    /feeds/health feed_count must grow. Either number alone can be moved by something
    that is not a new feed, so the test pins both."""
    n_adapters = [fake_adapter(f"fake_{i}", "ai", STREAM, [obs(url=f"https://e.test/{i}")])
                  for i in range(3)]

    assert register_sources(store=store, adapters=n_adapters) == 3
    await collect_once(store=store, adapters=n_adapters, run_ms=T0)
    before = await _health_payload(store)
    assert before["feed_count"] == 3
    assert before["source_count"] == 3

    n_plus_1 = n_adapters + [fake_adapter("fake_new", "markets", SNAPSHOT,
                                          [price_obs("BTC", 100.0)])]
    assert register_sources(store=store, adapters=n_plus_1) == 4
    await collect_once(store=store, adapters=n_plus_1, run_ms=T0 + 60_000)
    after = await _health_payload(store)
    assert after["feed_count"] == 4, "a new feed must be visible in health"
    assert after["source_count"] == 4, "and in the sources table"
    assert "fake_new" in after["feeds"]


async def test_a_silently_skipped_adapter_is_distinguishable_from_a_healthy_one(store):
    """The failure this acceptance exists to catch: a registered adapter that never
    runs. It must never read as `healthy`."""
    from engine.monitor.collect import reset_seen_this_process
    reset_seen_this_process()
    registered = [fake_adapter(f"fake_{i}", "ai", STREAM, [obs(url=f"https://e.test/{i}")])
                  for i in range(4)]
    register_sources(store=store, adapters=registered, run_ms=T0)
    await collect_once(store=store, adapters=registered[:3], run_ms=T0)  # one never ran

    payload = await _health_payload(store)
    assert payload["source_count"] == 4
    assert payload["feed_count"] == 4, "the skipped source is REPORTED, not omitted"
    assert payload["feeds"]["fake_3"]["status"] == "never_run"
    assert payload["feeds"]["fake_3"]["ran_this_process"] is False
    assert payload["counts"]["never_run"] == 1
    assert payload["counts"]["delivering"] == 3, "three, not four"
    assert payload["counts"]["not_run_this_process"] == 1
    assert "healthy" not in payload["counts"] or payload["counts"]["healthy"] == 3


async def test_feed_health_survives_a_restart(store, tmp_path):
    """The point of persisting feed_runs: a fresh process must report what the last
    run actually did. Memory-only health reported an empty dict after a restart, and
    an empty dict looks exactly like every feed being fine."""
    path = store.path
    await collect_once(
        store=store,
        adapters=[fake_adapter("fake_ai", "ai", STREAM, [obs()]),
                  fake_adapter("fake_hc", "healthcare", STREAM, [], status="error",
                               error="HTTP 500", http_status=500)],
        run_ms=T0)
    store.close()

    reopened = Store(path)
    try:
        health = health_from_persisted_runs(reopened)
        assert set(health) == {"fake_ai", "fake_hc"}
        assert health["fake_hc"]["status"] == "error"
        assert health["fake_hc"]["http_status"] == 500
        assert health["fake_hc"]["last_ok_at"] is None, "a feed that never delivered"
        assert health["fake_ai"]["last_ok_at"] is not None
        assert health["fake_ai"]["items_accepted"] == 1
    finally:
        reopened.close()


def test_a_source_that_fails_forever_still_reports_its_last_good_run(store):
    """`last_ok_at` must track the last DELIVERY, not the last attempt — otherwise a
    feed broken since Tuesday reads as freshly checked and therefore fine.

    The runs are recorded with EXPLICIT timestamps a week apart. Driving this through
    `collect_once` instead would stamp both with wall-clock `now_ms()`, and two runs in
    the same millisecond make 'last delivery' and 'last attempt' numerically identical —
    the test would then pass whichever value the code returned, which is no test at
    all. (Found by the canary for this behaviour failing to fire.)"""
    store.record_feed_run("fake_ai", T0, T0, "healthy", received=1, accepted=1)
    store.record_feed_run("fake_ai", T0 + 7 * DAY, T0 + 7 * DAY, "error",
                          http_status=503, error="HTTP 503")

    health = health_from_persisted_runs(store)["fake_ai"]
    assert health["status"] == "error"
    assert health["checked_at"] == T0 + 7 * DAY, "it WAS checked, a week later"
    assert health["last_ok_at"] == T0, "but it last DELIVERED a week ago"


# ── adapter metadata + fallbacks ───────────────────────────────────────────────

# The nine adapters that existed at the Phase 1 branch point. Named explicitly rather
# than read off ADAPTERS: a parallel lane is ADDING adapters, and a test that iterates
# the live registry would silently change population underneath its own assertion.
_PHASE_0_5_SOURCE_IDS = (
    "arxiv", "cisa_kev", "coingecko", "federal_register", "gdelt", "openai_news",
    "openfda", "state_dept_advisories", "treasury_yields",
)


def test_the_nine_phase_0_5_adapters_declare_their_display_name_and_domain():
    """Strict over a NAMED population of nine, not over 'every adapter' — the count is
    part of the assertion so growing the registry cannot quietly weaken it."""
    from engine.monitor.adapters import ADAPTERS
    by_id = {getattr(m, "SOURCE_ID", ""): m for m in ADAPTERS}
    missing = [s for s in _PHASE_0_5_SOURCE_IDS if s not in by_id]
    assert not missing, f"adapter(s) vanished from the registry: {missing}"

    checked = 0
    for source_id in _PHASE_0_5_SOURCE_IDS:
        meta = source_meta(by_id[source_id])
        assert meta["display_name"] and meta["display_name"] != source_id, source_id
        assert "." in meta["canonical_domain"], source_id
        checked += 1
    assert checked == 9, "the checked-count, stated so a skip cannot hide"


def test_every_registered_adapter_yields_usable_source_metadata():
    """Registry-wide, and DELIBERATELY weaker: a new adapter is allowed to arrive
    without the Phase 1 constants (contract), so this asserts only that the registry
    can describe it — never that it carries a label this lane did not write."""
    from engine.monitor.adapters import ADAPTERS
    assert len(ADAPTERS) >= 9
    for module in ADAPTERS:
        meta = source_meta(module)
        assert meta["source_id"] and meta["source_id"] != "unknown", module
        assert meta["display_name"], module
        assert meta["kind"] in (STREAM, SNAPSHOT), module


def test_an_adapter_meeting_only_the_0_5_contract_still_registers(store):
    """A parallel lane adds adapters. One that predates the Phase 1 constants must be
    a missing LABEL, never a dead registry — the fallbacks are the source_id and the
    domain parsed from a real URL it produced."""
    legacy = fake_adapter("legacy_src", "politics", STREAM, [])
    assert not hasattr(legacy, "DISPLAY_NAME")
    legacy.URL = "https://www.example.gov/api/v1/things?x=1"

    meta = source_meta(legacy)
    assert meta["display_name"] == "legacy_src"
    assert meta["canonical_domain"] == "example.gov", "www. stripped, path dropped"
    assert register_sources(store=store, adapters=[legacy]) == 1
    assert store.list_sources()[0]["display_name"] == "legacy_src"


def test_source_meta_falls_back_to_a_sample_observation_url():
    bare = types.SimpleNamespace(SOURCE_ID="bare", BEAT="ai", __name__="bare")
    assert source_meta(bare)["canonical_domain"] == ""
    assert source_meta(bare, "https://feeds.example.org/a/b")["canonical_domain"] \
        == "feeds.example.org"
    assert source_meta(bare)["kind"] == STREAM, "an unstated KIND is the safe one"


class _HostileModule:
    """A module whose attribute access RAISES. A bare SimpleNamespace with fields
    missing is not hostile enough: `getattr` defaults absorb it, nothing ever throws,
    and the test passes with or without the guard. (Found by the canary for this
    behaviour failing to fire.)"""
    __name__ = "hostile"

    def __getattr__(self, name):
        raise RuntimeError(f"module import is half-broken: {name}")


def test_the_registry_does_not_crash_on_a_broken_module(store):
    """One malformed module must not stop the others registering."""
    broken = _HostileModule()
    with pytest.raises(RuntimeError):
        broken.SOURCE_ID  # the canary's own control: this really does explode

    good = fake_adapter("fake_ai", "ai", STREAM, [], DISPLAY_NAME="Fine",
                        CANONICAL_DOMAIN="ok.test")
    count = register_sources(store=store, adapters=[broken, good])
    assert count == 1
    assert {r["source_id"] for r in store.list_sources()} == {"fake_ai"}


# ── retention ──────────────────────────────────────────────────────────────────

def _seed_for_prune(store):
    old = obs(url="https://example.test/old", title="Old news")
    fresh = obs(url="https://example.test/fresh", title="Fresh news")
    store.upsert_observations([old], T0 - 400 * DAY)
    store.upsert_observations([old.__class__(**{**old.__dict__, "title": "Old news v2"})],
                              T0 - 399 * DAY)
    store.upsert_observations([fresh], T0 - DAY)
    store.record_feed_run("fake_ai", T0 - 400 * DAY, T0 - 400 * DAY, "healthy",
                          received=1, accepted=1)
    store.record_feed_run("fake_ai", T0 - DAY, T0 - DAY, "healthy", received=1, accepted=1)
    store.save_brief("2025-07-01", T0 - 400 * DAY, T0 - 400 * DAY, "# ancient",
                     "published", created_ms=T0 - 400 * DAY)
    return obs_id_for(old), obs_id_for(fresh)


def test_prune_deletes_past_the_horizon_and_keeps_the_briefs(store):
    old_id, fresh_id = _seed_for_prune(store)
    assert store.count_observations() == 2
    assert store.count_revisions() == 1

    counts = store.prune(T0 - 365 * DAY)

    assert counts["observations"] == 1
    assert counts["revisions"] == 1
    assert counts["feed_runs"] == 1
    assert counts["stories"] == 1
    assert store.get(old_id) is None
    assert store.get(fresh_id) is not None
    assert store.count_revisions() == 0
    assert store.count_stories() == 1
    assert [r["obs_id"] for r in store.conn.execute(
        "SELECT obs_id FROM story_observations")] == [fresh_id]
    # Briefs are the product. They are never pruned, however old.
    assert store.get_brief("2025-07-01")["markdown"] == "# ancient"
    assert len(store.latest_feed_runs()) == 1


def test_prune_ages_an_observation_on_last_seen_not_first_seen(store):
    """A KEV entry first seen two years ago and still republished today is CURRENT.
    Pruning it on its birthday would delete it and let it return tomorrow as NEW."""
    long_lived = obs(url="https://example.test/kev")
    store.upsert_observations([long_lived], T0 - 500 * DAY)
    store.upsert_observations([long_lived], T0)  # still being reported

    store.prune(T0 - 365 * DAY)

    row = store.get(obs_id_for(long_lived))
    assert row is not None, "still-current rows must survive their first_seen date"
    assert row["first_seen_ms"] == T0 - 500 * DAY


def test_prune_once_uses_the_configured_retention_and_reports_counts(store, monkeypatch):
    # Patch the CONFIG object `schedule` actually holds: another test in this suite
    # reloads engine.config, after which engine.config.CONFIG is a DIFFERENT object
    # from the one this module imported at boot, and patching the wrong one passes
    # silently in isolation and fails in the full run.
    from engine.monitor import schedule as schedule_mod
    _seed_for_prune(store)
    monkeypatch.setattr(schedule_mod.CONFIG, "retention_days", 365)

    result = prune_once(store=store, now_ms_=T0)

    assert result["retention_days"] == 365
    assert result["cutoff_ms"] == T0 - 365 * DAY
    assert result["observations"] == 1
    assert store.count_observations() == 1


def test_prune_once_with_a_long_retention_deletes_nothing(store, monkeypatch):
    """A control: the prune must be doing arithmetic on the horizon, not deleting on
    a schedule. With retention wider than the data, every count is zero."""
    from engine.monitor import schedule as schedule_mod
    _seed_for_prune(store)
    monkeypatch.setattr(schedule_mod.CONFIG, "retention_days", 3650)

    result = prune_once(store=store, now_ms_=T0)

    assert result["observations"] == 0
    assert result["feed_runs"] == 0
    assert store.count_observations() == 2


# ── read routes ────────────────────────────────────────────────────────────────

async def _route(store, fn, *args, **kw):
    from engine.monitor import store as store_mod
    previous = store_mod._STORE
    store_mod.set_store(store)
    try:
        return await fn(*args, **kw)
    finally:
        store_mod.set_store(previous)


async def test_stories_route_filters_by_beat_and_orders_by_last_change(store):
    from engine.server import stories as stories_route
    store.upsert_observations([price_obs("BTC", 100.0)], T0, kind=SNAPSHOT)
    store.upsert_observations([obs()], T0 + 60_000, kind=STREAM)
    store.upsert_observations([price_obs("BTC", 200.0)], T0 + 120_000, kind=SNAPSHOT)

    everything = await _route(store, stories_route)
    assert everything["count"] == 2
    assert everything["stories"][0]["story_key"] == "fake_mkt|BTC", "newest change first"

    markets = await _route(store, stories_route, beat="markets")
    assert markets["count"] == 1
    assert markets["stories"][0]["beat"] == "markets"
    assert (await _route(store, stories_route, beat="politics"))["count"] == 0


async def test_story_route_returns_the_links_and_the_revision_history(store):
    from fastapi import HTTPException

    from engine.server import story as story_route
    for i, p in enumerate([1.0, 2.0, 3.0]):
        store.upsert_observations([price_obs("BTC", p)], T0 + i * 1000, kind=SNAPSHOT)

    payload = await _route(store, story_route, story_id_for("fake_mkt|BTC"))
    assert payload["obs_ids"] == [obs_id_for(price_obs("BTC", 1.0))]
    assert [r["changed"]["extra.price"] for r in payload["revisions"]] \
        == [[1.0, 2.0], [2.0, 3.0]]

    with pytest.raises(HTTPException) as caught:
        await _route(store, story_route, "no-such-story")
    assert caught.value.status_code == 404


async def test_retention_runs_even_when_the_daily_brief_is_disabled(monkeypatch):
    """Defect D6. The prune used to be one line inside the brief loop, gated on
    `brief_enabled` and sharing its `try`. With BRIEF_ENABLED=false retention never
    ran at all, and a disk filling up is not a failure anyone traces back to a brief
    setting. Asserted by running the real scheduler with briefs OFF."""
    import asyncio

    from engine.monitor import schedule as schedule_mod

    called: list = []
    monkeypatch.setattr(schedule_mod, "prune_once",
                        lambda: (called.append("prune"), {"observations": 7})[1])
    monkeypatch.setattr(schedule_mod, "next_fire",
                        lambda *a, **k: datetime.now(timezone.utc))
    monkeypatch.setattr(schedule_mod.CONFIG, "brief_enabled", False)

    scheduler = schedule_mod.BriefScheduler()
    scheduler.start()
    try:
        assert scheduler._task is None, "briefs are off"
        assert scheduler._prune_task is not None, "retention is not optional"
        for _ in range(60):
            await asyncio.sleep(0.05)
            if called:
                break
    finally:
        await scheduler.stop()

    assert called == ["prune"]
    assert scheduler.last_prune == {"observations": 7}


async def test_a_failing_brief_does_not_skip_the_prune(monkeypatch):
    """The two used to share one `try`, so a brief that raised took the prune with it."""
    import asyncio

    from engine.monitor import schedule as schedule_mod

    called: list = []

    async def exploding_run_once():
        called.append("brief")
        raise RuntimeError("the LLM provider is down")

    monkeypatch.setattr(schedule_mod, "run_once", exploding_run_once)
    monkeypatch.setattr(schedule_mod, "prune_once",
                        lambda: (called.append("prune"), {"observations": 0})[1])
    monkeypatch.setattr(schedule_mod, "next_fire",
                        lambda *a, **k: datetime.now(timezone.utc))
    monkeypatch.setattr(schedule_mod.CONFIG, "brief_enabled", True)

    scheduler = schedule_mod.BriefScheduler()
    scheduler.start()
    try:
        for _ in range(60):
            await asyncio.sleep(0.05)
            if "prune" in called and "brief" in called:
                break
    finally:
        await scheduler.stop()

    assert "brief" in called, "the brief really did run and really did fail"
    assert "prune" in called, "and retention happened anyway"


# ══ defects found by the Phase 1 adversarial verifier (2026-08-29) ═════════════

# ── D1a: one broken adapter module must not silence the registry ──────────────

def test_a_broken_adapter_module_does_not_take_the_registry_down(tmp_path, monkeypatch):
    """D1a, reproduced then guarded. A real syntax error in ONE module used to make
    the package import fail atomically: `_load_adapters()` went 13 -> 0 behind a single
    WARNING, and /feeds/health then served the stale `sources` rows as all-healthy.
    One typo silenced every feed while the monitor reported itself green.

    The registry is rebuilt here from a REAL directory of real module files, imported
    for real — a mocked importer would only test my idea of how imports fail."""
    import importlib
    import sys

    pkg = tmp_path / "probe_adapters"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        (pathlib.Path("engine/monitor/adapters/__init__.py").read_text()
         .replace('_ORDER = (', '_ORDER = ("good_one", "good_two", "broken")  # noqa\n_UNUSED = (')))
    body = ('SOURCE_ID = "{sid}"\nBEAT = "ai"\nKIND = "stream"\n'
            'DISPLAY_NAME = "{sid}"\nCANONICAL_DOMAIN = "e.test"\n'
            'async def fetch(client):\n    return None\n')
    (pkg / "good_one.py").write_text(body.format(sid="good_one"))
    (pkg / "good_two.py").write_text(body.format(sid="good_two"))
    (pkg / "broken.py").write_text('SOURCE_ID = "broken"\nthis is not valid python(((\n')

    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m.startswith("probe_adapters")]:
        del sys.modules[name]
    registry = importlib.import_module("probe_adapters")

    names = {m.SOURCE_ID for m in registry.ADAPTERS}
    assert names == {"good_one", "good_two"}, "the healthy modules still loaded"
    assert [n for n, _ in registry.IMPORT_FAILURES] == ["broken"]
    assert "SyntaxError" in registry.IMPORT_FAILURES[0][1], "and it is NAMED"
    # The count of module FILES is unchanged by the failure — that is the number the
    # registry shrinking has to be measured against.
    assert len(registry.discover_module_names()) == 3


def test_a_module_that_misses_the_adapter_contract_is_a_failure_not_a_silent_drop(tmp_path,
                                                                                  monkeypatch):
    """A file that imports cleanly but has no `fetch` cannot be called. Dropping it
    quietly would be the same silent shrink by another route."""
    import importlib
    import sys

    pkg = tmp_path / "probe_adapters2"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        pathlib.Path("engine/monitor/adapters/__init__.py").read_text())
    (pkg / "halfbaked.py").write_text('SOURCE_ID = "halfbaked"\nBEAT = "ai"\n')

    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m.startswith("probe_adapters2")]:
        del sys.modules[name]
    registry = importlib.import_module("probe_adapters2")

    assert registry.ADAPTERS == []
    assert registry.IMPORT_FAILURES[0][0] == "halfbaked"
    assert "KIND" in registry.IMPORT_FAILURES[0][1] and "fetch" in registry.IMPORT_FAILURES[0][1]


async def test_an_import_failure_becomes_a_visible_errored_source(store):
    """The registry knowing is not enough — it has to reach /feeds/health by name."""
    good = [fake_adapter("fake_ai", "ai", STREAM, [obs()])]
    register_sources(store=store, adapters=good,
                     import_failures=[("un_press", "SyntaxError: '(' was never closed")],
                     run_ms=T0)
    await collect_once(store=store, adapters=good, run_ms=T0)

    payload = await _health_payload(store)
    assert payload["feeds"]["un_press"]["status"] == "import_error"
    assert "SyntaxError" in payload["feeds"]["un_press"]["error"]
    assert payload["counts"]["import_error"] == 1
    assert payload["counts"]["delivering"] == 1, "one delivering, not two"


def test_health_publishes_the_module_count_so_a_shrunken_registry_is_visible():
    from engine.monitor.adapters import ADAPTERS
    from engine.monitor.collect import discovered_adapter_count
    assert discovered_adapter_count() == len(ADAPTERS) >= 13, \
        "module files on disk and registered adapters agree when nothing is broken"


# ── D1b: staleness ────────────────────────────────────────────────────────────

def test_a_source_that_stopped_running_goes_stale_instead_of_staying_healthy(store):
    """D1b. A retired adapter kept serving its last good run as `latest` forever:
    `checked_at` was in the payload but nothing compared it to the clock, so an
    adapter that stopped a week ago still reported `healthy`."""
    store.upsert_source("delta", "Delta", "ai", STREAM)
    store.record_feed_run("delta", T0, T0, "healthy", received=5, accepted=5)

    fresh = health_from_persisted_runs(store, now_ms_=T0 + 60_000,
                                       stale_after_ms=10 * 60_000)
    assert fresh["delta"]["status"] == "healthy"

    later = health_from_persisted_runs(store, now_ms_=T0 + 7 * DAY,
                                       stale_after_ms=10 * 60_000)
    assert later["delta"]["status"] == "stale"
    assert later["delta"]["age_ms"] == 7 * DAY
    assert later["delta"]["last_ok_at"] == T0, "it DID deliver once; that is still true"
    assert health_counts(later)["delivering"] == 0
    assert health_counts(later)["stale"] == 1


def test_stale_threshold_comes_from_the_sense_interval(monkeypatch):
    """Three missed collections, not one slow fetch. Env-overridable."""
    import importlib

    import engine.config as cfg
    monkeypatch.setenv("SENSE_INTERVAL_SEC", "200")
    monkeypatch.delenv("FEED_STALE_AFTER_SEC", raising=False)
    assert importlib.reload(cfg).Config().feed_stale_after_sec == 600

    monkeypatch.setenv("FEED_STALE_AFTER_SEC", "45")
    assert importlib.reload(cfg).Config().feed_stale_after_sec == 45
    importlib.reload(cfg)


async def test_readyz_is_not_ready_when_every_source_is_stale(store, monkeypatch):
    """The readiness rule decided for D1b: ready means at least one source is
    delivering NOW. Every source stale = NOT ready, even though each succeeded once —
    that is exactly the state that used to report all-healthy while nothing collected.
    `last_feed_ok_ms` could not express it, because it never goes back down."""
    from engine.monitor import store as store_mod
    from engine.server import readyz
    from engine.state import STATE

    store.upsert_source("fake_ai", "A", "ai", STREAM)
    store.record_feed_run("fake_ai", T0, T0, "healthy", received=1, accepted=1)
    STATE.set_feed_health({"fake_ai": {"status": "healthy"}})

    previous = store_mod._STORE
    store_mod.set_store(store)
    try:
        monkeypatch.setattr("engine.config.CONFIG.feed_stale_after_sec", 600)
        # The clock is pinned rather than left as wall-time: T0 is a fixed 2025 epoch,
        # so a real `now` would make the run stale before the test began and both
        # branches would return 503 for the wrong reason.
        monkeypatch.setattr("engine.monitor.collect.now_ms", lambda: T0 + 60_000)
        fresh = await readyz()
        assert fresh.status_code == 200

        # Nothing changes except the clock moving past the horizon.
        monkeypatch.setattr("engine.monitor.collect.now_ms", lambda: T0 + 30 * DAY)
        stale = await readyz()
        assert stale.status_code == 503, "a monitor that stopped collecting is NOT ready"
        assert b'"feeds_stale":1' in stale.body
    finally:
        store_mod.set_store(previous)
        STATE.set_feed_health({})


# ── D2: provenance enforced at the spine boundary ─────────────────────────────

@pytest.mark.parametrize("bad,reason", [
    (dict(url=""), "empty url"),
    (dict(url="   "), "empty url"),
    (dict(source_id=""), "empty source_id"),
    (dict(source_id="   "), "empty source_id"),
    (dict(beat="not_a_beat"), "beat"),
    (dict(url="javascript:alert(1)"), "scheme"),
    (dict(url="data:text/html,x"), "scheme"),
])
def test_malformed_observations_are_rejected_not_stored(store, bad, reason):
    """D2. All seven of these were ACCEPTED before, and four landed on disk in the
    verifier's probe. `NOT NULL` does not catch an empty string, and the invariant
    was held only by thirteen adapters each carrying their own `if not url: continue`
    — the fourteenth that forgot would have written broken rows silently."""
    counts = store.upsert_observations([obs(**bad)], T0)

    assert counts["rejected"] == 1, f"should have been rejected: {bad}"
    assert counts["new"] == 0
    assert store.count_observations() == 0, "nothing reached the disk"
    assert reason in " ".join(counts["rejected_reasons"])


def test_a_rejected_record_does_not_sink_the_rest_of_its_run(store):
    good = obs(url="https://example.test/ok")
    counts = store.upsert_observations([obs(url=""), good, obs(beat="nope")], T0)

    assert counts == {"new": 1, "changed": 0, "seen": 1, "rejected": 2,
                      "rejected_reasons": counts["rejected_reasons"]}
    assert store.count_observations() == 1
    assert store.get(obs_id_for(good)) is not None


async def test_rejections_are_surfaced_on_the_run_and_persisted(store):
    """A rejection nobody can see is the same defect one layer down: `accepted` must
    mean STORED, and the count has to survive a restart."""
    path = store.path
    leaky = fake_adapter("fake_ai", "ai", STREAM,
                         [obs(url="https://example.test/ok"), obs(url=""),
                          obs(beat="not_a_beat")])
    runs = await collect_once(store=store, adapters=[leaky], run_ms=T0)

    assert runs[0].received == 3
    assert runs[0].accepted == 1, "accepted counts what was STORED"
    assert runs[0].rejected == 2
    store.close()

    reopened = Store(path)
    try:
        health = health_from_persisted_runs(reopened, now_ms_=T0)
        assert health["fake_ai"]["items_received"] == 3
        assert health["fake_ai"]["items_accepted"] == 1
        assert health["fake_ai"]["items_rejected"] == 2
    finally:
        reopened.close()


async def test_the_whole_db_provenance_invariant_holds_against_a_hostile_adapter(store):
    """Acceptance 3, re-armed. The old version only inspected rows its own well-behaved
    fakes produced, so it could not have caught an adapter that misbehaved."""
    hostile = fake_adapter("fake_bad", "ai", STREAM, [
        obs(source_id="fake_bad", url=""),
        obs(source_id="fake_bad", url="javascript:alert(1)"),
        obs(source_id="", url="https://example.test/x"),
        obs(source_id="fake_bad", url="https://example.test/ok", beat="ai"),
    ])
    await collect_once(store=store, adapters=[hostile], run_ms=T0)

    rows = [dict(r) for r in store.conn.execute("SELECT * FROM observations")]
    assert len(rows) == 1, "three of four refused at the boundary"
    for row in rows:
        assert row["source_id"].strip()
        assert row["url"].lower().startswith("https://")
        assert row["beat"] in BEATS
        assert row["first_seen_ms"] and row["last_seen_ms"]


# ── D3: rows migrated from v1 that the feed never re-reports ──────────────────

def test_migrated_rows_are_linked_even_if_their_feed_never_reports_them_again(tmp_path):
    """D3, and this one was already visible in production: 58 deployed observations
    (50 gdelt, 8 state_dept_advisories) had no story link. They had aged out of their
    feeds before the upgrade, so the 'next collection pass links them' back-fill never
    reached them, and they were unreachable from /stories."""
    path = tmp_path / "monitor.db"
    _write_v1_db(path)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO observations (obs_id, source_id, beat, upstream_id, url, title,"
        " summary, content_hash, extra_json, source_ts_ms, first_seen_ms, last_seen_ms,"
        " changed_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("aged_out_gdelt_row_01", "gdelt", "politics", None, "https://e.test/g",
         "A story that scrolled off the feed", "", "h", "{}", None,
         T0 - 30 * DAY, T0 - 30 * DAY, T0 - 30 * DAY))
    conn.commit()
    conn.close()

    s = Store(path)
    try:
        # `sources` is empty at open, so nothing is linked yet on a guess.
        assert s.count_unlinked_observations() == 2

        s.upsert_source("gdelt", "GDELT", "politics", STREAM)
        s.upsert_source("old_src", "Old", "ai", SNAPSHOT)
        assert s.link_unlinked_observations() == 2
        assert s.count_unlinked_observations() == 0

        keys = {row["story_key"] for row in s.list_stories()}
        assert "old_src|up-1" in keys, "a snapshot source keeps its grouped identity"
        assert "aged_out_gdelt_row_01" in keys, "a stream source is 1:1"
        # The story is as old as its observation, not as old as the repair.
        gdelt_story = [r for r in s.list_stories()
                       if r["story_key"] == "aged_out_gdelt_row_01"][0]
        assert gdelt_story["first_seen_ms"] == T0 - 30 * DAY
    finally:
        s.close()


def test_store_open_does_not_guess_a_kind_for_an_unknown_source(tmp_path):
    """Linking at open time with a `stream` guess would mint a WRONG 1:1 story for a
    snapshot source, and a wrong story is worse than a missing one: the real pass can
    create the missing one, but it can never correct the wrong one."""
    path = tmp_path / "monitor.db"
    _write_v1_db(path)
    s = Store(path)
    try:
        assert s.count_stories() == 0, "no sources known, so no guess is made"
        assert s.count_unlinked_observations() == 1
    finally:
        s.close()

    # Once the source IS known, the next open links it with the right kind.
    s = Store(path)
    s.upsert_source("old_src", "Old", "ai", SNAPSHOT)
    s.close()
    s = Store(path)
    try:
        assert s.count_unlinked_observations() == 0
        assert s.list_stories()[0]["story_key"] == "old_src|up-1"
    finally:
        s.close()


def test_register_sources_sweeps_up_rows_from_a_retired_adapter(store):
    """A source whose adapter has been deleted will never appear in `sources`, so the
    known-sources-only rule at open time can never reach it. Boot sweeps the rest with
    the 1:1 fallback, which is the safe kind: it cannot merge two distinct things."""
    store.conn.execute(
        "INSERT INTO observations (obs_id, source_id, beat, upstream_id, url, title,"
        " summary, content_hash, extra_json, source_ts_ms, first_seen_ms, last_seen_ms,"
        " changed_at_ms) VALUES ('retired_row_1','retired_src','ai',NULL,"
        "'https://e.test/r','R','','h','{}',NULL,?,?,?)", (T0, T0, T0))
    store.conn.commit()
    assert store.count_unlinked_observations() == 1

    register_sources(store=store, adapters=[fake_adapter("fake_ai", "ai", STREAM, [])],
                     run_ms=T0)

    assert store.count_unlinked_observations() == 0
    assert store.list_stories()[0]["story_key"] == "retired_row_1"


def test_the_link_on_unchanged_path_is_guarded(store):
    """The verifier's fifth canary had no test at all: removing the link-on-unchanged
    path left 213 passing. This closes that hole directly."""
    o = obs()
    store.upsert_observations([o], T0)
    store.conn.execute("DELETE FROM story_observations")
    store.conn.execute("DELETE FROM stories")
    store.conn.commit()
    assert store.count_unlinked_observations() == 1

    store.upsert_observations([o], T0 + 1000)  # byte-identical: the UNCHANGED path

    assert store.count_unlinked_observations() == 0, \
        "an unchanged re-report must still (re)establish the story link"
    assert store.count_stories() == 1


# ── D5: the migration's real guarantee ────────────────────────────────────────

def test_a_half_migrated_database_heals_on_reopen(tmp_path):
    """D5. `executescript` force-commits, so `_migrate`'s rollback cannot undo DDL and
    an interrupted migration leaves a partial schema committed. The property that
    makes that safe is not atomicity — it is that every statement is IF NOT EXISTS and
    the version row is written LAST, so a reopen finishes the job. This asserts the
    guarantee the code actually offers, rather than the one the docstring used to
    claim."""
    path = tmp_path / "monitor.db"
    _write_v1_db(path)

    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE sources (source_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
          beat TEXT NOT NULL, kind TEXT NOT NULL,
          canonical_domain TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
          terms_note TEXT NOT NULL DEFAULT '');
    """)  # v2 interrupted after ONE table, no schema_version row
    conn.commit()
    tables_mid = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "sources" in tables_mid and "stories" not in tables_mid
    assert "schema_version" not in tables_mid, "the version row is written last"

    s = Store(path)
    try:
        assert s.schema_version == SCHEMA_VERSION
        tables = {r["name"] for r in s.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"sources", "feed_runs", "revisions", "stories", "story_observations",
                "schema_version"} <= tables
        assert s.get("legacy_obs_id_0001")["title"] == "Legacy row", "data intact"
    finally:
        s.close()


# ── D6: retention scope ───────────────────────────────────────────────────────

def test_prune_ages_out_spend_rows_but_never_briefs(store):
    """Spend rows age out — the monthly cap only ever reads the last month, so a
    year-old row is dead weight. Briefs are the product and are kept regardless."""
    store.record_spend("brief", "m", 0.01, ts_ms=T0 - 400 * DAY)
    store.record_spend("brief", "m", 0.02, ts_ms=T0 - DAY)
    store.save_brief("2025-07-01", T0 - 400 * DAY, T0 - 400 * DAY, "# ancient",
                     "published", created_ms=T0 - 400 * DAY)

    counts = store.prune(T0 - 365 * DAY)

    assert counts["llm_spend"] == 1
    assert store.spend_since(0) == pytest.approx(0.02)
    assert store.get_brief("2025-07-01")["markdown"] == "# ancient"


def test_a_failed_brief_never_commits_over_a_real_one(store):
    """The no-op early return used to call commit(), ending whatever transaction
    another method had opened on this shared connection."""
    store.save_brief("2026-08-28", T0, T0, "# the real brief", "published")
    store.save_brief("2026-08-28", T0, T0, "", "failed")

    row = store.get_brief("2026-08-28")
    assert row["status"] == "published"
    assert row["markdown"] == "# the real brief"
