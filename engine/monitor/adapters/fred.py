"""FRED — equity indices and WTI crude, from the St. Louis Fed.

Verified 2026-08-29: docs/feed-verification.md#fred. This closes the markets
coverage gap recorded in Phase 0.5 (no equity index, no oil) — `coingecko` covers
crypto and a gold proxy, `frankfurter` FX, `treasury_yields` the curve.

KIND is "snapshot": the instrument list is the full current state each fetch.

Plan §5.11 — identity is the SERIES ID, never the level. upstream_id is "SP500";
the value lives only in extra["price"] and the title carries no number, so a
moving index cannot manufacture a new observation.

**These are daily CLOSE values, not live quotes**, and they lag. The timestamp is
the observation's own date from the payload, never fetch time, so a Sunday fetch
honestly reports Friday's close. DCOILWTICO (EIA-sourced) runs a further two to
three business days behind the equity series — observed 2026-08-29: equities at
2026-08-28, WTI at 2026-08-25. extra["value_kind"] and extra["observation_date"]
say so explicitly.

**No gold series.** The LBMA fixings FRED used to carry
(GOLDAMGBD228NLBM / GOLDPMGBD228NLBM) now return "The series does not exist", and
a FRED series search for a gold price returns only volatility, PPI and trade-price
indices — no spot price. Evidence in docs/feed-verification.md#fred. Gold stays on
coingecko's PAXG proxy rather than shipping a stale number.

**Key handling.** FRED requires a registered api_key. It is read from the
FRED_API_KEY env var at fetch time; unset is a clean status="error", never a guess
and never a raise. The key is a query parameter, so every string that could carry
it off this module — the error message, any log line — goes through `scrub()`
first, which redacts the value itself and not merely the query string. The
module-level URL constant is the keyless endpoint, so nothing in the repo, the
fixture or the source tree holds a key.

**Terms.** FRED API Terms of Use permit this; the required attribution notice is
carried in TERMS_NOTE and in every observation's extra["fred_notice"]. Three of the
four series are third-party COPYRIGHTED (S&P Dow Jones for SP500/DJIA, NASDAQ OMX
for NASDAQCOM) and their notes prohibit reproduction without written permission,
so each observation carries extra["redistribution"] — "restricted" for those three,
"public_domain" for the EIA-sourced WTI series. A brief that ever leaves personal
use must respect that field. Full verdict: docs/feed-verification.md#fred.
"""
from __future__ import annotations

import json
import os

from ..models import AdapterRun, Observation
from . import _util

SOURCE_ID = "fred"
BEAT = "markets"
KIND = "snapshot"
DISPLAY_NAME = "FRED market indices (St. Louis Fed)"
CANONICAL_DOMAIN = "stlouisfed.org"
TERMS_NOTE = (
    "This product uses the FRED® API but is not endorsed or certified by the "
    "Federal Reserve Bank of St. Louis. SP500/DJIA (© S&P Dow Jones Indices) and "
    "NASDAQCOM (© NASDAQ OMX) are copyrighted third-party series: reproduction "
    "needs the owner's written permission. DCOILWTICO is US government (EIA) work."
)

ENV_KEY = "FRED_API_KEY"

# Keyless endpoint. The api_key is appended only inside fetch(), never stored here,
# so this constant is safe to print, commit and assert on.
URL = "https://api.stlouisfed.org/fred/series/observations"

_PAGE = "https://fred.stlouisfed.org/series/{}"

# Enough rows to step back over a run of market holidays without a second call.
_LIMIT = 10

# series id -> (display title, unit, instrument kind, redistribution)
SERIES = {
    "SP500": ("S&P 500", "index", "equity_index", "restricted"),
    "DJIA": ("Dow Jones Industrial Average", "index", "equity_index", "restricted"),
    "NASDAQCOM": ("NASDAQ Composite", "index", "equity_index", "restricted"),
    "DCOILWTICO": ("Crude oil, WTI spot (Cushing, OK)", "usd_per_barrel", "oil",
                   "public_domain"),
}

_NOTICE = ("This product uses the FRED® API but is not endorsed or certified by "
           "the Federal Reserve Bank of St. Louis.")


def scrub(text: str, key: str | None) -> str:
    """Redact the API key VALUE, not just a query string.

    `_util.safe_error` already blanks anything after a "?", which covers the
    common case of an exception quoting the request URL. This is the second
    layer: it redacts the secret itself, so a message that carries the key
    without a "?" in front of it — a provider echoing it back, a header dump —
    still cannot leak it.
    """
    if key:
        text = text.replace(key, "<redacted>")
    return text


def series_url(series_id: str, key: str) -> str:
    return (f"{URL}?series_id={series_id}&api_key={key}&file_type=json"
            f"&sort_order=desc&limit={_LIMIT}")


def latest_value(payload: bytes) -> tuple[float, str] | None:
    """Newest observation that carries a real number, with its own date.

    FRED emits "." for a day the series has no value (market holidays — observed
    live at 2025-12-25 and 2026-01-01 on SP500), so the newest ROW is not always
    the newest VALUE. Returns None when no row in the window has one.
    """
    data = json.loads(payload)
    rows = data.get("observations")
    if not isinstance(rows, list):
        raise ValueError("payload has no observations list")
    for row in rows:  # sort_order=desc — newest first
        if not isinstance(row, dict):
            continue
        raw = row.get("value")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue  # "." — no value published for that date
        date = row.get("date")
        if isinstance(date, str) and date:
            return value, date
    return None


def observation(series_id: str, value: float, date: str) -> Observation:
    title, unit, instrument_kind, redistribution = SERIES[series_id]
    return Observation(
        source_id=SOURCE_ID,
        # No level in the title — identity is the series.
        title=title,
        url=_PAGE.format(series_id),
        beat=BEAT,
        summary="",
        upstream_id=series_id,
        source_ts_ms=_util.ms_from_date(date),
        extra={
            "price": value,
            "symbol": series_id,
            "unit": unit,
            "instrument_kind": instrument_kind,
            "observation_date": date,
            "value_kind": "daily_close",
            "redistribution": redistribution,
            "fred_notice": _NOTICE,
        },
    )


async def fetch(client) -> AdapterRun:
    key = (os.environ.get(ENV_KEY) or "").strip()
    if not key:
        return _util.error_run(
            SOURCE_ID, f"{ENV_KEY} not configured — no key, no call made")

    observations: list[Observation] = []
    received = 0
    first_failure: AdapterRun | None = None
    http_status: int | None = None

    for series_id in SERIES:
        received += 1
        resp, failure = await _util.get(client, SOURCE_ID, series_url(series_id, key))
        if failure is not None:
            failure.error = scrub(failure.error or "", key)
            if first_failure is None:
                first_failure = failure
            continue
        http_status = resp.status_code
        try:
            found = latest_value(resp.content)
        except Exception as exc:  # noqa: BLE001 — adapters never raise
            if first_failure is None:
                first_failure = _util.error_run(
                    SOURCE_ID, scrub(_util.safe_error(exc), key), resp.status_code)
            continue
        if found is None:
            continue  # every row in the window was "." — counted, not accepted
        observations.append(observation(series_id, *found))

    # Nothing usable AND something actually broke -> report the breakage, not "empty".
    # An empty-but-well-formed payload still reports "empty", as the contract requires.
    if not observations and first_failure is not None:
        first_failure.received = received
        return first_failure
    return _util.finish(SOURCE_ID, observations, received,
                        http_status if http_status is not None else
                        (first_failure.http_status if first_failure else None))
