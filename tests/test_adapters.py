"""Fixture-driven adapter tests. No network: every response is a recorded fixture.

Fixtures in tests/fixtures/ are real responses captured 2026-08-28; provenance and
the exact URL called for each are in docs/feed-verification.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from engine.monitor.adapters import ADAPTERS
from engine.monitor.models import BEATS
from engine.monitor.adapters import (
    arxiv,
    cisa_kev,
    coingecko,
    federal_register,
    gdelt,
    openai_news,
    openfda,
    state_dept_advisories,
    treasury_yields,
)

FIXTURES = Path(__file__).parent / "fixtures"

# adapter module -> (fixture filename, content type)
CASES = {
    arxiv: ("arxiv.xml", "application/atom+xml"),
    openai_news: ("openai_news.xml", "text/xml"),
    federal_register: ("federal_register.json", "application/json"),
    openfda: ("openfda.json", "application/json"),
    cisa_kev: ("cisa_kev.json", "application/json"),
    gdelt: ("gdelt.json", "application/json"),
    coingecko: ("coingecko.json", "application/json"),
    state_dept_advisories: ("state_dept_advisories.xml", "text/xml"),
    treasury_yields: ("treasury_yields.xml", "text/xml"),
}

# Minimum observations each fixture must yield, from the trimmed fixture contents.
MIN_OBSERVATIONS = {
    arxiv: 3,
    openai_news: 3,
    federal_register: 5,
    openfda: 6,
    cisa_kev: 3,
    gdelt: 5,
    coingecko: 3,
    state_dept_advisories: 4,
    treasury_yields: 4,  # 4 tenors from the newest entry
}

ALL_MODULES = list(CASES)


def fixture_bytes(module) -> bytes:
    return (FIXTURES / CASES[module][0]).read_bytes()


def client_returning(module, *, status: int = 200, body: bytes | None = None,
                     raises: Exception | None = None) -> httpx.AsyncClient:
    """An AsyncClient whose transport replays a fixture (or fails) instead of dialing out."""
    payload = fixture_bytes(module) if body is None else body

    def handler(request: httpx.Request) -> httpx.Response:
        if raises is not None:
            raise raises
        return httpx.Response(
            status, content=payload,
            headers={"content-type": CASES[module][1]},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def empty_body(module) -> bytes:
    """A well-formed but item-free payload in the same format as the real one."""
    name = CASES[module][0]
    if name.endswith(".json"):
        raw = json.loads(fixture_bytes(module))
        if module is coingecko:
            return b"{}"
        for key in ("results", "vulnerabilities", "articles"):
            if key in raw:
                raw[key] = []
        return json.dumps(raw).encode()
    if module is arxiv:
        return b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    if module in (openai_news, state_dept_advisories):
        return b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    # treasury_yields: an OData feed with no entries
    return (b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" '
            b'xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"></feed>')


# --- registry / contract -------------------------------------------------------

# The beat each source is assigned to. Asserting obs.beat == module.BEAT is
# tautological — it cannot catch a source filed under the wrong beat — so the
# assignment itself is pinned here.
EXPECTED_BEATS = {
    "arxiv": "ai",
    "openai_news": "ai",
    "cisa_kev": "cybersecurity",
    "gdelt": "politics",
    "state_dept_advisories": "politics",
    "federal_register": "healthcare",
    "openfda": "healthcare",
    "coingecko": "markets",
    "treasury_yields": "markets",
}

EXPECTED_KINDS = {
    "arxiv": "stream",
    "openai_news": "stream",
    "cisa_kev": "snapshot",
    "gdelt": "stream",
    "state_dept_advisories": "snapshot",
    "federal_register": "stream",
    "openfda": "stream",
    "coingecko": "snapshot",
    "treasury_yields": "snapshot",
}


def test_each_source_is_filed_under_the_intended_beat_and_kind():
    assert {m.SOURCE_ID: m.BEAT for m in ADAPTERS} == EXPECTED_BEATS
    assert {m.SOURCE_ID: m.KIND for m in ADAPTERS} == EXPECTED_KINDS


def test_registry_covers_every_beat_and_obeys_the_module_contract():
    assert len(ADAPTERS) == len(ALL_MODULES)
    source_ids = [m.SOURCE_ID for m in ADAPTERS]
    assert len(set(source_ids)) == len(source_ids), "SOURCE_ID must be unique"
    for module in ADAPTERS:
        assert module.SOURCE_ID == module.SOURCE_ID.lower()
        assert module.BEAT in BEATS
        assert module.KIND in ("stream", "snapshot")
        assert callable(module.fetch)
    assert {m.BEAT for m in ADAPTERS} == set(BEATS), "every beat needs a source"


# --- happy path ----------------------------------------------------------------

@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_fixture_parses_into_valid_observations(module):
    async with client_returning(module) as client:
        run = await module.fetch(client)

    assert run.status == "healthy", run.error
    assert run.source_id == module.SOURCE_ID
    assert run.http_status == 200
    assert run.error is None
    assert len(run.observations) >= MIN_OBSERVATIONS[module]
    assert run.accepted == len(run.observations)
    assert run.received >= run.accepted

    for obs in run.observations:
        assert obs.source_id == module.SOURCE_ID
        assert obs.beat == module.BEAT
        assert obs.beat in BEATS
        assert obs.title.strip(), "title is required"
        assert obs.url.startswith("http"), f"url must be canonical: {obs.url!r}"
        assert obs.source_ts_ms is None or obs.source_ts_ms > 0


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_upstream_id_is_stable_across_two_identical_fetches(module):
    async with client_returning(module) as client:
        first = await module.fetch(client)
    async with client_returning(module) as client:
        second = await module.fetch(client)

    def identity(run):
        return [(o.upstream_id or o.url) for o in run.observations]

    assert identity(first) == identity(second)


# --- failure paths -------------------------------------------------------------

@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_http_500_becomes_error_without_raising(module):
    async with client_returning(module, status=500) as client:
        run = await module.fetch(client)

    assert run.status == "error"
    assert run.http_status == 500
    assert run.error and "500" in run.error
    assert run.observations == []


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_timeout_becomes_error_without_raising(module):
    boom = httpx.ReadTimeout("timed out")
    async with client_returning(module, raises=boom) as client:
        run = await module.fetch(client)

    assert run.status == "error"
    assert run.observations == []
    assert run.error and "ReadTimeout" in run.error


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_empty_payload_becomes_empty(module):
    async with client_returning(module, body=empty_body(module)) as client:
        run = await module.fetch(client)

    assert run.status == "empty", run.error
    assert run.observations == []
    assert run.accepted == 0


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_malformed_payload_becomes_error_without_raising(module):
    async with client_returning(module, body=b"<<<not parseable>>>") as client:
        run = await module.fetch(client)

    assert run.status == "error"
    assert run.observations == []
    assert run.error


@pytest.mark.parametrize("module", ALL_MODULES, ids=lambda m: m.SOURCE_ID)
async def test_error_message_never_leaks_a_query_string(module):
    boom = httpx.ConnectError(
        "failed connecting to host?api_key=SUPERSECRET&token=abc123"
    )
    async with client_returning(module, raises=boom) as client:
        run = await module.fetch(client)

    assert run.status == "error"
    assert "SUPERSECRET" not in run.error
    assert "abc123" not in run.error


# --- per-source specifics ------------------------------------------------------

async def test_federal_register_classifies_document_type():
    async with client_returning(federal_register) as client:
        run = await federal_register.fetch(client)

    types = {o.extra["doc_type"] for o in run.observations}
    assert types <= {"proposed_rule", "final_rule", "notice", "presidential", "unknown"}
    # The fixture holds more than one raw type, so a classifier that collapses
    # everything to a single label cannot pass this.
    raw_types = {o.extra["raw_type"] for o in run.observations}
    assert len(raw_types) > 1, f"fixture must exercise >1 type, got {raw_types}"
    assert len(types) == len(raw_types), f"{raw_types} must not collapse into {types}"
    for obs in run.observations:
        # Each row's label must follow that row's own raw type, not a constant.
        assert obs.extra["doc_type"] == federal_register.classify(obs.extra["raw_type"])
        assert obs.upstream_id, "document_number is the stable id"
        assert obs.extra["agencies"], "agency attribution is required"


def test_federal_register_classify_maps_the_api_vocabulary():
    assert federal_register.classify("Proposed Rule") == "proposed_rule"
    assert federal_register.classify("Rule") == "final_rule"
    assert federal_register.classify("Notice") == "notice"
    assert federal_register.classify("Presidential Document") == "presidential"
    assert federal_register.classify(None) == "unknown"
    # An unrecognised type is passed through, never silently called a notice.
    assert federal_register.classify("Correction") == "correction"


async def test_cisa_kev_uses_cve_id_as_identity_and_links_to_nvd():
    async with client_returning(cisa_kev) as client:
        run = await cisa_kev.fetch(client)

    assert cisa_kev.KIND == "snapshot", "GONE must be meaningful for KEV"
    for obs in run.observations:
        assert obs.upstream_id.startswith("CVE-")
        assert obs.url == f"https://nvd.nist.gov/vuln/detail/{obs.upstream_id}"


@pytest.mark.parametrize("module", [coingecko, treasury_yields],
                         ids=lambda m: m.SOURCE_ID)
async def test_market_price_is_never_part_of_identity(module):
    """Plan §5.11: identity is the symbol; a moving price must not create a new row."""
    async with client_returning(module) as client:
        run = await module.fetch(client)

    assert module.KIND == "snapshot"
    assert run.observations

    for obs in run.observations:
        assert obs.upstream_id, "market instruments must carry a symbol id"
        assert "price" in obs.extra, "price belongs in extra"
        price = obs.extra["price"]
        assert isinstance(price, (int, float))
        # The price must appear nowhere that feeds identity. A bare digit check on
        # the symbol would be meaningless — "UST3M" legitimately contains a "3" —
        # so this asserts the rendered price, and the moved-price case below is
        # what actually proves identity is independent of the quote.
        rendered = f"{price}"
        assert rendered not in obs.title
        assert rendered not in obs.upstream_id
        assert rendered not in obs.url

    # Same symbols, different prices -> identical identity.
    moved = _with_moved_prices(module)
    async with client_returning(module, body=moved) as client:
        after = await module.fetch(client)

    before_ids = [o.upstream_id for o in run.observations]
    after_ids = [o.upstream_id for o in after.observations]
    assert before_ids == after_ids
    assert [o.extra["price"] for o in run.observations] != \
           [o.extra["price"] for o in after.observations], "prices should have moved"


def _with_moved_prices(module) -> bytes:
    """The same payload with every quote changed — identity must not move with it."""
    raw = fixture_bytes(module)
    if module is coingecko:
        data = json.loads(raw)
        for row in data.values():
            row["usd"] = round(row["usd"] * 1.11, 4)
        return json.dumps(data).encode()
    # treasury_yields: bump every BC_* rate in the XML
    import re
    text = raw.decode()
    def bump(match):
        return f'{match.group(1)}{float(match.group(2)) + 0.25:.2f}{match.group(3)}'
    return re.sub(r'(<d:BC_[A-Z0-9_]+ m:type="Edm.Double">)([\d.]+)(</d:BC_)',
                  bump, text).encode()


async def test_coingecko_labels_the_gold_proxy_as_a_proxy():
    async with client_returning(coingecko) as client:
        run = await coingecko.fetch(client)

    paxg = [o for o in run.observations if o.upstream_id == "PAXG"]
    assert paxg, "PAXG should be present in the fixture"
    assert paxg[0].extra["instrument_kind"] == "gold_proxy"
    assert "proxy" in paxg[0].title.lower()


async def test_treasury_takes_the_newest_entry_in_the_month():
    async with client_returning(treasury_yields) as client:
        run = await treasury_yields.fetch(client)

    dates = {o.extra["record_date"] for o in run.observations}
    assert len(dates) == 1, f"a snapshot is one date, got {dates}"

    # It must be the NEWEST date in the feed, not merely the first entry. Derived
    # from the fixture so this keeps checking the property if the fixture changes.
    import re as _re
    published = _re.findall(r"<d:NEW_DATE[^>]*>([\d-]{10})", fixture_bytes(treasury_yields).decode())
    assert len(set(published)) > 1, "fixture must hold several dates to make this meaningful"
    assert dates == {max(published)}, f"expected newest {max(published)}, got {dates}"
    symbols = {o.upstream_id for o in run.observations}
    assert symbols == {"UST3M", "UST2Y", "UST10Y", "UST30Y"}


async def test_arxiv_identity_ignores_the_version_suffix():
    async with client_returning(arxiv) as client:
        run = await arxiv.fetch(client)

    for obs in run.observations:
        assert "v" not in obs.upstream_id.split(".")[-1], obs.upstream_id
        assert obs.summary, "arXiv entries carry an abstract"


async def test_gdelt_falls_back_to_url_identity_and_dedups():
    async with client_returning(gdelt) as client:
        run = await gdelt.fetch(client)

    assert all(o.upstream_id is None for o in run.observations)
    urls = [o.url for o in run.observations]
    assert len(set(urls)) == len(urls), "duplicate urls must be collapsed"

    doubled = json.loads(fixture_bytes(gdelt))
    doubled["articles"] = doubled["articles"] + doubled["articles"]
    async with client_returning(gdelt, body=json.dumps(doubled).encode()) as client:
        run2 = await gdelt.fetch(client)

    assert run2.received == 10
    assert run2.accepted == run.accepted, "dedup by url"


async def test_openfda_url_is_deterministic_from_the_record_id():
    async with client_returning(openfda) as client:
        run = await openfda.fetch(client)

    for obs in run.observations:
        assert obs.upstream_id
        assert obs.upstream_id in obs.url
        assert '"' not in obs.url, "a bare quote is not valid in a URL"
        assert obs.extra["doc_type"] == "enforcement_action"


async def test_openfda_keeps_records_that_have_no_recall_number():
    """A real Class I Baxter recall (event_id 99463) carried no recall_number.

    Dropping it would silently lose a genuine healthcare event, so identity falls
    back to event_id. The fixture holds that exact record.
    """
    payload = json.loads(fixture_bytes(openfda))
    no_recall = [r for r in payload["results"] if not (r.get("recall_number") or "").strip()]
    assert no_recall, "fixture must still contain the recall_number-less record"

    async with client_returning(openfda) as client:
        run = await openfda.fetch(client)

    assert run.accepted == run.received == len(payload["results"])
    by_id = {o.upstream_id for o in run.observations}
    assert no_recall[0]["event_id"] in by_id
    fallback = [o for o in run.observations if o.upstream_id == no_recall[0]["event_id"]][0]
    assert "event_id" in fallback.url


async def test_state_dept_extracts_the_advisory_level():
    """The level is the operational signal: Level 2 -> Level 4 is the briefable change."""
    async with client_returning(state_dept_advisories) as client:
        run = await state_dept_advisories.fetch(client)

    levels = sorted(o.extra["advisory_level"] for o in run.observations)
    assert levels == [1, 2, 3, 4], f"fixture covers every level, got {levels}"
    for obs in run.observations:
        assert obs.extra["advisory_label"], "the level's wording is part of the signal"
        assert obs.extra["country_code"], "country code comes from dc:identifier"
        assert obs.upstream_id and "," in obs.upstream_id
        assert "<" not in obs.summary, "CDATA HTML must be stripped for the brief"


def test_state_dept_parse_level_reads_the_title():
    assert state_dept_advisories.parse_level("Qatar - Level 3: Reconsider Travel") == (3, "Reconsider Travel")
    assert state_dept_advisories.parse_level("Ukraine - Level 4: Do Not Travel") == (4, "Do Not Travel")
    assert state_dept_advisories.parse_level("No level here") == (None, "")


def test_state_dept_handles_a_pubdate_with_no_time():
    """This feed stamps 'Fri, 28 Aug 2026' with no time.

    email.utils.parsedate_to_datetime rejects that form, so a naive RFC-822 parse
    loses every timestamp in the feed. The exception TYPE is version-dependent —
    Python 3.9 raises TypeError, 3.13 raises ValueError — so the adapter catches
    both and this asserts the rejection, not the type.
    """
    from email.utils import parsedate_to_datetime
    with pytest.raises((TypeError, ValueError)):
        parsedate_to_datetime("Fri, 28 Aug 2026")

    # Computed, not a magic constant: a date with no time is UTC midnight.
    from datetime import datetime, timezone
    midnight = datetime(2026, 8, 28, tzinfo=timezone.utc)
    assert state_dept_advisories._pubdate_ms("Fri, 28 Aug 2026") == int(midnight.timestamp() * 1000)

    # The normal form with a time must still work.
    noon = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)
    assert state_dept_advisories._pubdate_ms("Fri, 28 Aug 2026 12:00:00 +0000") == int(noon.timestamp() * 1000)
    assert state_dept_advisories._pubdate_ms("not a date") is None
    assert state_dept_advisories._pubdate_ms(None) is None


async def test_state_dept_identity_survives_a_level_change():
    """A country changing advisory level must be the SAME observation, changed."""
    raw = fixture_bytes(state_dept_advisories).decode()
    escalated = raw.replace("Level 1: Exercise Normal Precautions", "Level 4: Do Not Travel")
    assert escalated != raw

    async with client_returning(state_dept_advisories) as client:
        before = await state_dept_advisories.fetch(client)
    async with client_returning(state_dept_advisories, body=escalated.encode()) as client:
        after = await state_dept_advisories.fetch(client)

    assert [o.upstream_id for o in before.observations] == [o.upstream_id for o in after.observations]
    assert sorted(o.extra["advisory_level"] for o in before.observations) != \
           sorted(o.extra["advisory_level"] for o in after.observations)
