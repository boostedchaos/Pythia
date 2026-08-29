"""Frankfurter — ECB reference FX rates, USD base.

Verified 2026-08-28 and re-verified 2026-08-29: docs/feed-verification.md#frankfurter.
Keyless public API over the European Central Bank's published reference rates.

KIND is "snapshot": the whole pair list arrives each fetch, so a pair disappearing is
meaningful.

Plan §5.11 — identity is the PAIR, never the rate. upstream_id is "USD/EUR"; the rate
lives only in extra["price"] and the title carries no number, so a moving quote cannot
manufacture a new observation.

These are ECB *reference* rates, published once per business day (around 16:00 CET),
NOT a live tradable quote. The payload's own "date" field is the reference date and is
what source_ts_ms reports, so a weekend fetch honestly reports Friday's date rather than
looking fresh. extra["rate_kind"] says so explicitly.
"""
from __future__ import annotations

import json

from ..models import Observation
from . import _util

SOURCE_ID = "frankfurter"
BEAT = "markets"
KIND = "snapshot"
DISPLAY_NAME = "ECB reference FX (Frankfurter)"
CANONICAL_DOMAIN = "frankfurter.dev"

BASE = "USD"

# quote currency -> display name
QUOTES = {
    "EUR": "Euro",
    "JPY": "Japanese yen",
    "GBP": "Pound sterling",
    "CHF": "Swiss franc",
    "CNY": "Chinese yuan",
}

_API = "https://api.frankfurter.dev/v1/latest"
URL = f"{_API}?base={BASE}&symbols={','.join(QUOTES)}"


def pair_url(code: str) -> str:
    """Frankfurter has no per-pair web page; the canonical url is that pair's own
    query — deterministic and resolvable, never invented per fetch."""
    return f"{_API}?base={BASE}&symbols={code}"


def parse(payload: bytes) -> tuple[list[Observation], int]:
    data = json.loads(payload)
    rates = data.get("rates")
    if not isinstance(rates, dict):
        return [], 0
    reference_date = data.get("date")
    ts = _util.ms_from_date(reference_date) if isinstance(reference_date, str) else None

    out: list[Observation] = []
    received = 0
    for code, name in QUOTES.items():
        rate = rates.get(code)
        received += 1
        if not isinstance(rate, (int, float)):
            continue
        symbol = f"{BASE}/{code}"
        out.append(
            Observation(
                source_id=SOURCE_ID,
                # No rate in the title — identity is the pair.
                title=f"US dollar / {name} ({symbol})",
                url=pair_url(code),
                beat=BEAT,
                summary="",
                upstream_id=symbol,
                source_ts_ms=ts,
                extra={
                    "price": rate,
                    "base": BASE,
                    "quote": code,
                    "symbol": symbol,
                    "reference_date": reference_date,
                    "instrument_kind": "fx",
                    "rate_kind": "ecb_reference_daily",
                },
            )
        )
    return out, received


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
