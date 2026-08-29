"""US Treasury daily par yield curve — the macro rates the plan asks for (§8).

Verified 2026-08-28: docs/feed-verification.md#treasury_yields. Keyless; US federal
government work, public domain.

KIND is "snapshot": each fetch reports the current value of a fixed tenor list.

Plan §5.11 — identity is the TENOR symbol (e.g. "UST10Y"), never the yield. The
yield lives only in extra["price"]. The feed is an OData Atom document holding one
entry per publication date for the requested month; we take the newest entry only.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from ..models import Observation
from . import _util

SOURCE_ID = "treasury_yields"
BEAT = "markets"
KIND = "snapshot"
DISPLAY_NAME = "US Treasury par yield curve"
CANONICAL_DOMAIN = "home.treasury.gov"

BASE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value_month={month}"
)

ATOM = "{http://www.w3.org/2005/Atom}"
D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"

# XML property -> (symbol, display name)
TENORS = {
    "BC_3MONTH": ("UST3M", "US Treasury 3-month par yield"),
    "BC_2YEAR": ("UST2Y", "US Treasury 2-year par yield"),
    "BC_10YEAR": ("UST10Y", "US Treasury 10-year par yield"),
    "BC_30YEAR": ("UST30Y", "US Treasury 30-year par yield"),
}

PAGE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "TextView?type=daily_treasury_yield_curve"
)


def current_month(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y%m")


def previous_month(now: datetime | None = None) -> str:
    ref = now or datetime.now(timezone.utc)
    return (ref.replace(day=1) - timedelta(days=1)).strftime("%Y%m")


def url_for(month: str) -> str:
    return BASE.format(month=month)


def _props(entry: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for content in entry.iter(f"{ATOM}content"):
        for props in content:
            for field in props:
                out[field.tag.replace(D, "")] = (field.text or "").strip()
    return out


def parse(payload: bytes) -> tuple[list[Observation], int]:
    root = ET.fromstring(payload)
    entries = root.findall(f"{ATOM}entry")
    rows = [_props(e) for e in entries]
    rows = [r for r in rows if r.get("NEW_DATE")]
    if not rows:
        return [], 0
    # Entries are not guaranteed ordered; the newest publication date is the snapshot.
    latest = max(rows, key=lambda r: r["NEW_DATE"])
    ts = _util.ms_from_iso(latest["NEW_DATE"])
    # `received` counts the instruments the snapshot offers, not the number of
    # publication dates in the month, so it stays comparable with `accepted`.
    received = sum(1 for field in TENORS if latest.get(field))
    out: list[Observation] = []
    for field, (symbol, name) in TENORS.items():
        raw = latest.get(field)
        if not raw:
            continue
        try:
            yield_pct = float(raw)
        except ValueError:
            continue
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=name,  # no number in the title — identity is the tenor symbol
                url=PAGE,
                beat=BEAT,
                summary="",
                upstream_id=symbol,
                source_ts_ms=ts,
                extra={
                    "price": yield_pct,
                    "unit": "percent_per_annum",
                    "symbol": symbol,
                    "instrument_kind": "rate",
                    "record_date": latest["NEW_DATE"][:10],
                },
            )
        )
    return out, received


async def fetch(client):
    # Early in a month the current-month feed exists but holds no publication yet,
    # so fall back to the previous month rather than reporting an empty curve.
    last_run = None
    for month in (current_month(), previous_month()):
        resp, failure = await _util.get(client, SOURCE_ID, url_for(month))
        if failure is not None:
            return failure
        try:
            observations, received = parse(resp.content)
        except Exception as exc:
            return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
        last_run = _util.finish(SOURCE_ID, observations, received, resp.status_code)
        if observations:
            return last_run
    return last_run
