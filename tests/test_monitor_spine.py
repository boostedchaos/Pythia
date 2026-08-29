"""Phase 0.5 spine: identity, persistence, and deterministic delta.

Every test here guards a specific plan acceptance criterion. Each was proven to
FAIL with the guarded behaviour reverted — see the lane report for the canaries.
No network: adapters are fakes defined in this file.
"""
from __future__ import annotations

import types

import pytest

from engine.monitor import delta as delta_mod
from engine.monitor.collect import collect_once, health_from_runs
from engine.monitor.models import SNAPSHOT, STREAM, AdapterRun, Observation
from engine.monitor.store import Store, obs_id_for

DAY = 24 * 60 * 60 * 1000
T0 = 1_756_000_000_000          # a fixed epoch-ms so windows are exact, never "now"


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


def fake_adapter(source_id: str, beat: str, kind: str, observations, status="healthy",
                 error=None, raises=False):
    """A module-shaped object: the contract is attributes + `async fetch(client)`."""
    async def fetch(client):
        if raises:
            raise RuntimeError("adapter blew up")
        return AdapterRun(source_id=source_id, status=status, observations=list(observations),
                          error=error, received=len(observations), accepted=len(observations))
    return types.SimpleNamespace(SOURCE_ID=source_id, BEAT=beat, KIND=kind, fetch=fetch,
                                 __name__=f"fake.{source_id}")


# ── identity ───────────────────────────────────────────────────────────────────

def test_same_record_twice_is_one_row_with_a_stable_id(store):
    """The planted-duplicate criterion at the storage layer. State is READ BACK
    from SQLite rather than trusting the return value of the write."""
    o = obs()
    store.upsert_observations([o], T0)
    store.upsert_observations([o], T0 + 1000)

    assert store.count_observations() == 1
    row = store.get(obs_id_for(o))
    assert row is not None
    assert row["obs_id"] == obs_id_for(o)
    assert row["first_seen_ms"] == T0, "first_seen must never be rewritten"
    assert row["last_seen_ms"] == T0 + 1000
    assert row["changed_at_ms"] == T0, "an unchanged re-fetch is not a change"


def test_identity_ignores_the_price(store):
    """Plan §5.11: the price is an attribute, never part of the key."""
    a = obs(source_id="markets", beat="markets", upstream_id="BTC", title="BTC 100",
            url="https://example.test/btc", extra={"price": 100.0})
    b = obs(source_id="markets", beat="markets", upstream_id="BTC", title="BTC 110",
            url="https://example.test/btc", extra={"price": 110.0})
    assert obs_id_for(a) == obs_id_for(b)


def test_natural_key_falls_back_url_then_title():
    no_id = obs(upstream_id=None, url="https://example.test/x", title="T")
    no_url = obs(upstream_id=None, url="", title="  Mixed   CASE  Title ")
    same_title = obs(upstream_id=None, url="", title="mixed case title")
    assert obs_id_for(no_id) != obs_id_for(no_url)
    assert obs_id_for(no_url) == obs_id_for(same_title), "title key must be normalized"


# ── delta ──────────────────────────────────────────────────────────────────────

async def test_planted_duplicate_produces_one_bullet(store):
    """Plan acceptance: 'a synthetic run with a planted duplicate produces one
    bullet, not two.' The same natural key is fetched TWICE in one run."""
    from engine.monitor.brief import select

    # The realistic plant: one story, two renderings. A byte-identical repeat would
    # also collapse under a content-based key, so it cannot tell the two apart —
    # only a differing headline proves the NATURAL KEY is what deduplicates.
    dup_a = obs(upstream_id="dup-1", title="Regulator opens inquiry")
    dup_b = obs(upstream_id="dup-1", title="Regulator opens inquiry — updated",
                summary="now with a second paragraph")
    adapter = fake_adapter("fake_ai", "ai", STREAM, [dup_a, dup_b, dup_a])
    await collect_once(store=store, adapters=[adapter], run_ms=T0)

    assert store.count_observations() == 1

    d = delta_mod.compute(store, T0 - DAY, T0 + 1)
    assert len(d["new"]) == 1
    assert len(select(d)) == 1, "one story must yield one bullet"


async def test_unchanged_story_is_not_new_on_day_two(store):
    """Plan acceptance: 'an unchanged story from yesterday never appears under NEW.'"""
    adapter = fake_adapter("fake_ai", "ai", STREAM, [obs(upstream_id="story-1")])
    await collect_once(store=store, adapters=[adapter], run_ms=T0)
    await collect_once(store=store, adapters=[adapter], run_ms=T0 + DAY)

    day_two = delta_mod.compute(store, T0, T0 + DAY + 1)
    assert day_two["new"] == [], "an unchanged story reappeared as NEW"
    assert day_two["changed"] == [], "an unchanged story reappeared as CHANGED"

    day_one = delta_mod.compute(store, T0 - DAY, T0)
    assert len(day_one["new"]) == 1, "it must still be NEW in the window it arrived in"


async def test_market_price_move_is_changed_not_new(store):
    """Plan §5.11 end to end: a moved price is a CHANGE to one row."""
    def adapter_at(price):
        return fake_adapter("markets", "markets", SNAPSHOT, [
            obs(source_id="markets", beat="markets", upstream_id="BTC",
                title=f"BTC {price}", url="https://example.test/btc",
                extra={"price": price})])

    await collect_once(store=store, adapters=[adapter_at(100.0)], run_ms=T0)
    await collect_once(store=store, adapters=[adapter_at(110.0)], run_ms=T0 + DAY)

    assert store.count_observations() == 1, "a price move created a second row"
    d = delta_mod.compute(store, T0, T0 + DAY + 1)
    assert d["new"] == []
    assert len(d["changed"]) == 1
    assert d["changed"][0]["title"] == "BTC 110.0"


async def test_snapshot_dropout_is_gone(store):
    """GONE is meaningful only for snapshot sources: an instrument that vanished
    from the latest full id-set."""
    two = fake_adapter("markets", "markets", SNAPSHOT, [
        obs(source_id="markets", beat="markets", upstream_id="BTC", title="BTC",
            url="https://example.test/btc"),
        obs(source_id="markets", beat="markets", upstream_id="DOGE", title="DOGE",
            url="https://example.test/doge")])
    one = fake_adapter("markets", "markets", SNAPSHOT, [
        obs(source_id="markets", beat="markets", upstream_id="BTC", title="BTC",
            url="https://example.test/btc")])

    await collect_once(store=store, adapters=[two], run_ms=T0)
    await collect_once(store=store, adapters=[one], run_ms=T0 + DAY)

    d = delta_mod.compute(store, T0, T0 + DAY + 1)
    assert [g["upstream_id"] for g in d["gone"]] == ["DOGE"]


async def test_stream_source_never_reports_gone(store):
    """A rolling feed drops old items by design; calling that 'GONE' is noise."""
    two = fake_adapter("fake_ai", "ai", STREAM, [
        obs(upstream_id="a", title="A"), obs(upstream_id="b", title="B")])
    one = fake_adapter("fake_ai", "ai", STREAM, [obs(upstream_id="a", title="A")])
    await collect_once(store=store, adapters=[two], run_ms=T0)
    await collect_once(store=store, adapters=[one], run_ms=T0 + DAY)
    assert delta_mod.compute(store, T0, T0 + DAY + 1)["gone"] == []


async def test_partially_failed_snapshot_run_does_not_manufacture_gone(store):
    """A feed outage must read as an outage, never as 'everything disappeared'.

    The PARTIAL failure is the dangerous shape: a paginated fetch that dies halfway
    returns status="error" WITH a truncated list. Recording that truncated list as
    the source's full current state reports every missing item as GONE — inventing
    news out of a network fault. (A total failure returns nothing and is therefore
    self-limiting; this is the case that actually needs the guard.)"""
    def snapshot_of(symbols, **kw):
        return fake_adapter("markets", "markets", SNAPSHOT, [
            obs(source_id="markets", beat="markets", upstream_id=s, title=s,
                url=f"https://example.test/{s.lower()}") for s in symbols], **kw)

    await collect_once(store=store, adapters=[snapshot_of(["BTC", "DOGE", "ETH"])], run_ms=T0)
    await collect_once(store=store,
                       adapters=[snapshot_of(["BTC"], status="error", error="HTTP 503 mid-page")],
                       run_ms=T0 + DAY)

    assert delta_mod.compute(store, T0, T0 + DAY + 1)["gone"] == []

    # A total failure is also silent, for the same reason.
    await collect_once(store=store,
                       adapters=[snapshot_of([], status="error", error="HTTP 503")],
                       run_ms=T0 + 2 * DAY)
    assert delta_mod.compute(store, T0, T0 + 2 * DAY + 1)["gone"] == []


# ── collection + health ────────────────────────────────────────────────────────

async def test_a_raising_adapter_becomes_an_error_run_and_does_not_stop_the_others(store):
    good = fake_adapter("fake_ai", "ai", STREAM, [obs(upstream_id="ok")])
    bad = fake_adapter("fake_sec", "cybersecurity", STREAM, [], raises=True)

    runs = await collect_once(store=store, adapters=[bad, good], run_ms=T0)
    by_id = {r.source_id: r for r in runs}

    assert by_id["fake_sec"].status == "error"
    assert "RuntimeError" in (by_id["fake_sec"].error or "")
    assert by_id["fake_ai"].status == "healthy"
    assert store.count_observations() == 1, "the good adapter still persisted"


async def test_feed_health_surface_includes_adapter_runs(store):
    """A dead direct feed must be visible on /feeds/health, not silent."""
    runs = await collect_once(
        store=store,
        adapters=[fake_adapter("fake_ai", "ai", STREAM, [obs()]),
                  fake_adapter("fake_hc", "healthcare", STREAM, [], status="error",
                               error="HTTP 500")],
        run_ms=T0)
    health = health_from_runs(runs)

    assert set(health) == {"fake_ai", "fake_hc"}
    assert health["fake_hc"]["status"] == "error"
    assert health["fake_hc"]["last_ok_at"] is None
    assert health["fake_ai"]["last_ok_at"] is not None
    # The shape /feeds/health already publishes — extended, not replaced.
    assert set(health["fake_ai"]) >= {"source", "path", "status", "error", "items_accepted"}


def test_a_monitor_pass_moves_the_freshness_clock():
    """Monitor mode builds no WorldBrief, so `world_refreshed_ms` would stay null
    forever — and a permanently blank freshness field looks exactly like a monitor
    that has stopped running."""
    from engine.state import EngineState
    st = EngineState()
    assert st.world_refreshed_ms is None
    st.note_monitor_pass(1812)
    assert st.world_refreshed_ms is not None
    assert st.observation_count == 1812


def test_state_reports_not_ready_when_every_adapter_failed():
    from engine.state import EngineState
    runs = [AdapterRun(source_id=f"s{i}", status="error", observations=[], error="boom")
            for i in range(5)]
    st = EngineState()
    st.set_feed_health(health_from_runs(runs))
    assert st.last_feed_ok_ms is None


# ── container-first config (plan §5.12) ────────────────────────────────────────

def test_config_reads_no_file_outside_the_deployment():
    """The engine used to read ~/.hermes/.env and ~/MiroFish/.env for credentials.
    Neither exists in a container, so a fresh deploy pointed at nothing and said so
    nowhere. Asserted against the SOURCE, because the behaviour is an absence and an
    absence cannot be observed by calling anything."""
    from pathlib import Path
    raw = (Path(__file__).resolve().parent.parent / "engine" / "config.py").read_text()
    # Comments are stripped first: the file explains WHY those reads were removed,
    # and a checker that trips over its own documentation is a false positive.
    code = "\n".join(ln for ln in raw.splitlines() if not ln.lstrip().startswith("#"))
    for forbidden in (".hermes", "MIROFISH", "MiroFish", "Path.home()", "11434"):
        assert forbidden not in code, f"config.py still references {forbidden}"
    # Prove the checker can still see something that IS there.
    assert "llm_base_url" in code


def test_llm_defaults_to_openrouter_and_never_invents_a_key(monkeypatch):
    import importlib

    import engine.config as cfg
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "OPENROUTER_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    cfg = importlib.reload(cfg)
    assert cfg.CONFIG.llm_base_url == "https://openrouter.ai/api/v1"
    assert cfg.CONFIG.llm_api_key == "", "a blank key must stay blank, not become 'ollama'"


def test_openrouter_key_env_var_is_honoured(monkeypatch):
    import importlib

    import engine.config as cfg
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-a-real-one")
    cfg = importlib.reload(cfg)
    assert cfg.CONFIG.llm_api_key == "test-key-not-a-real-one"
    assert cfg.CONFIG.swarm_api_key == "test-key-not-a-real-one"


def test_brief_defaults_match_the_contract(monkeypatch):
    import importlib

    import engine.config as cfg
    for var in ("BRIEF_HOUR_LOCAL", "BRIEF_TZ", "PYTHIA_LLM_MONTHLY_CAP_USD", "NTFY_URL",
                "NTFY_TOPIC"):
        monkeypatch.delenv(var, raising=False)
    cfg = importlib.reload(cfg)
    assert cfg.CONFIG.brief_hour_local == 7
    assert cfg.CONFIG.brief_tz == "America/Chicago"
    assert cfg.CONFIG.llm_monthly_cap_usd == 5.0
    assert cfg.CONFIG.ntfy_url == "https://ntfy.sh"


def test_config_summary_never_carries_a_secret(monkeypatch):
    import importlib

    import engine.config as cfg
    monkeypatch.setenv("NTFY_TOPIC", "a-secret-topic-value")
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-secret-key-value")
    cfg = importlib.reload(cfg)
    dumped = repr(cfg.CONFIG.summary())
    assert "a-secret-topic-value" not in dumped, "the ntfy topic IS the credential"
    assert "a-secret-key-value" not in dumped
    assert cfg.CONFIG.summary()["ntfy_configured"] is True


def test_schedule_next_fire_is_local_time(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from engine.monitor.schedule import next_fire
    tz = "America/Chicago"
    before = datetime(2026, 8, 29, 3, 0, tzinfo=ZoneInfo(tz))
    assert next_fire(before, 7, tz).hour == 7
    assert next_fire(before, 7, tz).day == 29
    after = datetime(2026, 8, 29, 9, 0, tzinfo=ZoneInfo(tz))
    assert next_fire(after, 7, tz).day == 30, "past today's hour must roll to tomorrow"


# ── spend bookkeeping ──────────────────────────────────────────────────────────

def test_unknown_cost_is_null_not_zero_and_is_counted_separately(store):
    """An unrecorded cost is unknown, not free. Estimating it would make the
    budget number look authoritative while being invented."""
    store.record_spend("brief", "m", 0.02, ts_ms=T0)
    store.record_spend("brief", "m", None, ts_ms=T0 + 1)

    assert store.spend_since(T0) == pytest.approx(0.02)
    assert store.spend_unknown_rows(T0) == 1
