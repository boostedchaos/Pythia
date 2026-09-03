"""Phase 0.5 brief gates — the criteria the plan says must be PROVEN, not assumed.

The LLM is a fake callable throughout: no key, no network, no cost. Each test was
run with its guard reverted and observed to fail (canaries in the lane report).
"""
from __future__ import annotations

import pytest

from engine.monitor import brief as brief_mod
from engine.monitor.brief import CitationError, LLMError, run_brief, validate_citations
from engine.monitor.models import AdapterRun, Observation
from engine.monitor.store import Store, obs_id_for

DAY = 24 * 60 * 60 * 1000
T0 = 1_756_000_000_000
YESTERDAY_MD = "# yesterday's brief\n\n- the previous day's only bullet\n"


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "monitor.db")
    yield s
    s.close()


@pytest.fixture(autouse=True)
def brief_config(monkeypatch):
    """Pin the settings the brief reads, so a developer's .env cannot change a result."""
    cfg = brief_mod.CONFIG
    monkeypatch.setattr(cfg, "brief_tz", "America/Chicago", raising=False)
    monkeypatch.setattr(cfg, "brief_model", "fake/model", raising=False)
    monkeypatch.setattr(cfg, "llm_monthly_cap_usd", 5.0, raising=False)
    return cfg


def seed(store, *, count=1, at_ms=T0, beat="ai", prefix="s"):
    """Put `count` fresh observations in the store and return their ids."""
    items = [Observation(source_id="fake_ai", title=f"Story {prefix}{i}",
                         url=f"https://example.test/{i}", beat=beat,
                         summary="what happened", upstream_id=f"{prefix}{i}")
             for i in range(count)]
    store.upsert_observations(items, at_ms)
    return [obs_id_for(o) for o in items]


def publish_yesterday(store, end_ms=T0 - 1):
    store.save_brief("2026-08-27", end_ms - DAY, end_ms, YESTERDAY_MD, "published",
                     model="fake/model", cost_usd=0.01, created_ms=end_ms)


def good_llm(calls: list):
    """A model that behaves: it cites only what it was sent."""
    async def _call(pack):
        calls.append(pack)
        return {"bullets": [{"beat": p["beat"], "text": f"Rewritten: {p['title']}",
                             "obs_ids": [p["obs_id"]]} for p in pack],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0012},
                "model": "fake/model"}
    return _call


async def no_notify(result):
    return {"sent": False, "reason": "test"}


# ── the citation gate (plan acceptance: 'a planted fabricated citation is rejected') ──

async def test_fabricated_citation_blocks_publication(store):
    seed(store, count=2)
    publish_yesterday(store)

    async def liar(pack):
        return {"bullets": [{"beat": "ai", "text": "Something the model made up",
                             "obs_ids": ["deadbeefdeadbeefdeadbeef"]}],
                "usage": {}, "model": "fake/model"}

    result = await run_brief(store=store, at_ms=T0 + 1, llm=liar, notify=no_notify)

    assert result["status"] == "failed"
    assert store.get_brief(result["brief_date"])["status"] == "failed"
    latest = store.latest_brief()
    assert latest["markdown"] == YESTERDAY_MD, "the fabricated brief replaced yesterday's"


async def test_a_real_id_that_was_not_sent_is_still_a_fabrication(store):
    """'In the evidence pack that was SENT', not 'in the database'. An id that
    exists but was never shown to the model is a lucky guess, not a citation."""
    hidden = Observation(source_id="fake_ai", title="Never selected",
                         url="https://example.test/hidden", beat="ai", upstream_id="hidden")
    store.upsert_observations([hidden], T0 - 10 * DAY)   # old: outside every window below
    sent = seed(store, count=1)
    publish_yesterday(store)

    async def cites_hidden(pack):
        return {"bullets": [{"beat": "ai", "text": "About something unsent",
                             "obs_ids": [obs_id_for(hidden)]}], "usage": {},
                "model": "fake/model"}

    result = await run_brief(store=store, at_ms=T0 + 1, llm=cites_hidden, notify=no_notify)
    assert result["status"] == "failed"
    assert store.get(obs_id_for(hidden)) is not None, "the id really does exist in the DB"
    assert store.latest_brief()["markdown"] == YESTERDAY_MD
    assert sent  # the pack that WAS sent held a different id


def test_validator_rejects_an_uncited_bullet():
    pack = [{"obs_id": "abc123", "beat": "ai", "kind": "new", "title": "t", "summary": ""}]
    with pytest.raises(CitationError, match="cites nothing"):
        validate_citations([{"beat": "ai", "text": "a claim", "obs_ids": []}], pack)
    with pytest.raises(CitationError, match="no bullets"):
        validate_citations([], pack)


# ── provider failure leaves yesterday intact ───────────────────────────────────

async def test_llm_transport_failure_leaves_yesterdays_brief_intact(store):
    seed(store, count=2)
    publish_yesterday(store)

    async def dead(pack):
        raise LLMError("HTTP 502")

    result = await run_brief(store=store, at_ms=T0 + 1, llm=dead, notify=no_notify)

    assert result["status"] == "failed"
    assert result["latest_unchanged"] is True
    assert store.latest_brief()["markdown"] == YESTERDAY_MD


async def test_a_failed_run_never_overwrites_a_brief_already_published_today(store):
    """Same calendar date, two runs: a later failure must not blank the morning's brief."""
    seed(store, count=1)
    calls: list = []
    ok = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm(calls), notify=no_notify)
    assert ok["status"] == "published"

    seed(store, count=1, at_ms=T0 + 2, beat="markets", prefix="later")

    async def dead(pack):
        raise LLMError("HTTP 502")

    failed = await run_brief(store=store, at_ms=T0 + 3, llm=dead, notify=no_notify)
    assert failed["status"] == "failed", "the second run must actually have had work to do"
    row = store.get_brief(ok["brief_date"])
    assert row["status"] == "published"
    assert row["markdown"] == ok["markdown"]


# ── budget ceiling ─────────────────────────────────────────────────────────────

async def test_at_the_cap_the_brief_is_deterministic_and_no_llm_is_called(store, brief_config):
    seed(store, count=3)
    store.record_spend("brief", "fake/model", 5.0, ts_ms=T0 - 1000)

    calls: list = []
    result = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm(calls), notify=no_notify)

    assert calls == [], "the LLM was called after the budget cap was reached"
    assert result["status"] == "deterministic"
    assert "budget" in result["markdown"].lower()
    assert result["bullets"] == 3
    assert store.latest_brief()["status"] == "deterministic"


async def test_below_the_cap_the_llm_runs(store):
    """The other side of the same switch — otherwise a permanently broken budget
    check would look identical to a working one."""
    seed(store, count=1)
    store.record_spend("brief", "fake/model", 0.5, ts_ms=T0 - 1000)
    calls: list = []
    result = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm(calls), notify=no_notify)
    assert len(calls) == 1
    assert result["status"] == "published"


async def test_cost_is_recorded_from_usage_and_never_estimated(store):
    seed(store, count=1)

    async def no_cost_field(pack):
        return {"bullets": [{"beat": "ai", "text": "t", "obs_ids": [pack[0]["obs_id"]]}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}, "model": "fake/model"}

    result = await run_brief(store=store, at_ms=T0 + 1, llm=no_cost_field, notify=no_notify)
    row = store.get_brief(result["brief_date"])

    assert result["cost_usd"] is None
    assert row["cost_usd"] is None, "an unknown cost must be NULL, not a guess"
    assert row["prompt_tokens"] == 10 and row["completion_tokens"] == 5
    assert store.spend_unknown_rows(0) == 1


# ── coverage warning ───────────────────────────────────────────────────────────

async def test_a_feed_outage_produces_a_visible_coverage_warning(store):
    seed(store, count=1)
    runs = [AdapterRun(source_id="fake_ai", status="healthy", observations=[]),
            AdapterRun(source_id="federal_register", status="error", observations=[],
                       error="HTTP 503")]

    result = await run_brief(store=store, at_ms=T0 + 1, adapter_runs=runs,
                             llm=good_llm([]), notify=no_notify)

    assert result["coverage_warnings"] == ["federal_register"]
    assert "Coverage warning" in result["markdown"]
    assert "federal_register" in result["markdown"]


async def test_no_warning_when_every_adapter_is_healthy(store):
    seed(store, count=1)
    runs = [AdapterRun(source_id="fake_ai", status="healthy", observations=[])]
    result = await run_brief(store=store, at_ms=T0 + 1, adapter_runs=runs,
                             llm=good_llm([]), notify=no_notify)
    assert "Coverage warning" not in result["markdown"]


# ── the published artifact ─────────────────────────────────────────────────────

async def test_published_brief_names_its_window_and_cites_every_bullet(store):
    ids = seed(store, count=2)
    publish_yesterday(store, end_ms=T0 - 1)
    result = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm([]), notify=no_notify)
    md = result["markdown"]

    assert result["status"] == "published"
    assert "Coverage window:" in md
    assert "UTC" in md and "America/Chicago" in md
    # the window starts where yesterday's brief ended — no gap, no double-count
    assert result["coverage_start_ms"] == T0 - 1
    for oid in ids:
        assert f"[{oid[:8]}](https://example.test/" in md, "a bullet lost its source URL"
    assert "## Ai" in md


async def test_urls_come_from_the_store_not_the_model(store):
    """The model never emits a URL. Even if it tries, the renderer ignores it."""
    ids = seed(store, count=1)

    async def sneaky(pack):
        return {"bullets": [{"beat": "ai", "text": "Read more at https://evil.test/phish",
                             "obs_ids": [pack[0]["obs_id"]], "url": "https://evil.test/phish"}],
                "usage": {}, "model": "fake/model"}

    result = await run_brief(store=store, at_ms=T0 + 1, llm=sneaky, notify=no_notify)
    assert f"[{ids[0][:8]}](https://example.test/0)" in result["markdown"]
    assert "](https://evil.test" not in result["markdown"], "a model-supplied link was linkified"


async def test_an_empty_window_publishes_an_honest_brief_without_calling_the_llm(store):
    calls: list = []
    result = await run_brief(store=store, at_ms=T0, llm=good_llm(calls), notify=no_notify)
    assert calls == []
    assert result["status"] == "deterministic"
    assert "No new, changed or removed observations" in result["markdown"]


async def test_selection_caps_bullets_per_beat(store):
    seed(store, count=20)
    result = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm([]), notify=no_notify)
    assert result["bullets"] == brief_mod.MAX_BULLETS_PER_BEAT


async def test_ntfy_failure_does_not_unpublish_the_brief(store):
    seed(store, count=1)

    async def broken_notify(result):
        raise RuntimeError("ntfy unreachable")

    result = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm([]), notify=broken_notify)
    assert result["status"] == "published"
    assert result["delivery"]["sent"] is False
    assert store.latest_brief()["status"] == "published"


def test_ntfy_summary_keeps_one_source_link_per_bullet_and_no_markdown_syntax():
    from engine.monitor import ntfy
    result = {"status": "published", "brief_date": "2026-08-29",
              "markdown": "## Ai\n\n- Something changed [abc12345](https://example.test/1)"
                          " [def67890](https://example.test/2)\n",
              "coverage_warnings": ["federal_register"]}
    title, body = ntfy._summarise(result)
    assert "1 item(s)" in title
    assert "https://example.test/1" in body, "the push must carry the bullet's first source URL"
    assert "https://example.test/2" not in body, "only the FIRST source URL per bullet"
    assert "](" not in body and "[abc12345]" not in body, "no markdown syntax in a plain push"
    assert body.index("Something changed") < body.index("https://example.test/1")
    assert "federal_register" in body


def test_ntfy_summary_always_keeps_the_and_more_footer():
    """The regression Kyle saw on 2026-09-02: a 26-item brief arrived as five
    bullets with NOTHING saying more existed, because the single trailing slice
    put the footer last and so cut it first."""
    from engine.monitor import ntfy
    # Bullets must be REAL-brief length (~170 chars incl. the URL line). With
    # short ones the old 900-char slice never bit and this test passed against
    # the very bug it exists to catch — confirmed by running it on the old code.
    md = "## Ai\n\n" + "".join(
        f"- Item number {i}: a realistic arXiv-length summary sentence that runs on"
        f" for a while because that is what these bullets actually look like in a"
        f" published brief [abc{i:05d}](https://example.test/{i})\n" for i in range(40))
    title, body = ntfy._summarise(
        {"status": "published", "brief_date": "2026-09-02",
         "markdown": md, "coverage_warnings": []})
    assert "40 item(s)" in title
    assert "more." in body, "the push must say how many items it did not show"
    shown = body.count("• Item number ")
    assert f"…and {40 - shown} more." in body, "the count must match what was shown"


def test_ntfy_summary_keeps_the_coverage_warning_under_pressure():
    """A coverage gap is a warning; it must outrank bullet text when space runs out."""
    from engine.monitor import ntfy
    md = "## Ai\n\n" + "".join(
        f"- Padding line {i} " + "x" * 200 + "\n" for i in range(40))
    _, body = ntfy._summarise(
        {"status": "published", "brief_date": "2026-09-02",
         "markdown": md, "coverage_warnings": ["federal_register", "cisa"]})
    assert "coverage gap" in body and "federal_register" in body


def test_ntfy_body_stays_under_the_attachment_threshold_and_never_cuts_mid_line():
    """>=4096 BYTES makes ntfy convert the message to an attachment (verified
    against ntfy.sh 2026-09-02), so the budget is bytes and the POST still
    returns 200 when it happens. Cuts must land on a bullet boundary."""
    from engine.monitor import ntfy
    md = "## Ai\n\n" + "".join(
        f"- Ünïcödé bullet {i} " + "é" * 150 +
        f" [abc{i:05d}](https://example.test/{i})\n" for i in range(60))
    _, body = ntfy._summarise(
        {"status": "published", "brief_date": "2026-09-02",
         "markdown": md, "coverage_warnings": []})
    assert len(body.encode("utf-8")) <= ntfy.MAX_BODY_BYTES < 4096
    for line in body.splitlines():
        if line.startswith("• Ünïcödé bullet "):
            assert line.endswith("é"), f"bullet cut mid-line: {line[-40:]!r}"


def test_ntfy_summary_survives_a_bullet_with_no_link():
    from engine.monitor import ntfy
    result = {"status": "published", "brief_date": "2026-08-29",
              "markdown": "## Ai\n\n- Linkless line\n", "coverage_warnings": []}
    _, body = ntfy._summarise(result)
    assert "Linkless line" in body and "http" not in body


# ── ntfy header encoding (found on the VM: published fine, delivered nothing) ──

def _capturing_transport(seen: list, status: int = 200):
    """A real httpx transport, so the request goes through httpx's OWN header
    encoding — which is where delivery actually broke. A test that only inspected
    our sanitizer would have passed while the VM kept failing."""
    import httpx

    async def handler(request):
        seen.append(request)
        return httpx.Response(status)
    return httpx.MockTransport(handler)


async def test_a_non_ascii_brief_is_actually_delivered(monkeypatch):
    """Regression. httpx encodes header values as ASCII, so the em dash in the push
    title raised UnicodeEncodeError before the request left the process. The brief
    published; nothing arrived."""
    from engine.monitor import ntfy
    monkeypatch.setattr(ntfy.CONFIG, "ntfy_topic", "topic-under-test", raising=False)

    seen: list = []
    result = {"status": "published", "brief_date": "2026-08-28",
              "markdown": "## Ai\n\n- Café raises prices — again ⚠ [abc12345](https://x.test/1)\n",
              "coverage_warnings": ["gdelt"]}

    delivery = await ntfy.send_brief(result, transport=_capturing_transport(seen))

    assert delivery["sent"] is True, f"delivery failed: {delivery}"
    assert len(seen) == 1
    title = seen[0].headers["Title"]
    assert title.isascii(), f"non-ascii survived into a header: {title!r}"
    assert "2026-08-28" in title
    # The body is sent as UTF-8 bytes and must keep its real characters.
    assert "Café".encode() in seen[0].content
    assert "—".encode() in seen[0].content


def test_ascii_header_folds_reads_and_strips_control_characters():
    from engine.monitor.ntfy import ascii_header
    assert ascii_header("brief — 3 items") == "brief - 3 items"
    assert ascii_header("Café ⚠ naïve → done") == "Cafe ! naive -> done"
    assert ascii_header("title\r\nX-Injected: evil") == "title X-Injected: evil"
    assert ascii_header("emoji 🎉 dropped") == "emoji dropped"
    assert ascii_header("plain ascii") == "plain ascii"


async def test_a_delivery_failure_still_leaves_the_brief_published(store, monkeypatch):
    """The VM's exact sequence: the brief is real, only the push failed."""
    from engine.monitor import ntfy
    monkeypatch.setattr(ntfy.CONFIG, "ntfy_topic", "topic-under-test", raising=False)
    seed(store, count=1)

    result = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm([]),
                             notify=lambda r: ntfy.send_brief(
                                 r, transport=_capturing_transport([], status=500)))
    assert result["status"] == "published"
    assert result["delivery"]["sent"] is False
    assert result["delivery"]["http_status"] == 500
    assert store.latest_brief()["status"] == "published"


async def test_resend_latest_redelivers_without_touching_the_llm(store, monkeypatch):
    """The operator's recovery path: re-push what is already stored."""
    from engine.monitor import ntfy
    monkeypatch.setattr(ntfy.CONFIG, "ntfy_topic", "topic-under-test", raising=False)
    seed(store, count=2)
    calls: list = []
    published = await run_brief(store=store, at_ms=T0 + 1, llm=good_llm(calls),
                                notify=no_notify)
    assert published["status"] == "published" and len(calls) == 1

    seen: list = []
    real_send = ntfy.send_brief
    monkeypatch.setattr(ntfy, "send_brief",
                        lambda r: real_send(r, transport=_capturing_transport(seen)))
    out = await ntfy.resend_latest(store=store)

    assert out["sent"] is True
    assert out["brief_date"] == published["brief_date"]
    assert len(calls) == 1, "resending must not call the model again"
    assert len(seen) == 1, "exactly one push"
    assert store.get_brief(published["brief_date"])["status"] == "published"


async def test_resend_latest_says_so_when_there_is_nothing_to_resend(store):
    from engine.monitor import ntfy
    out = await ntfy.resend_latest(store=store)
    assert out["sent"] is False
    assert "no published brief" in out["reason"]


# ── defensive parsing of the model's reply ─────────────────────────────────────

def test_parse_bullets_handles_fenced_json():
    body = {"choices": [{"message": {"content":
            '```json\n{"bullets": [{"beat":"ai","text":"t","obs_ids":["a1"]}]}\n```'}}]}
    assert brief_mod.parse_bullets(body) == [{"beat": "ai", "text": "t", "obs_ids": ["a1"]}]


def test_parse_bullets_rejects_prose_and_null_content():
    with pytest.raises(LLMError):
        brief_mod.parse_bullets({"choices": [{"message": {"content": "Sure! Here you go."}}]})
    with pytest.raises(LLMError, match="null content"):
        brief_mod.parse_bullets({"choices": [{"message": {"content": None}}]})
