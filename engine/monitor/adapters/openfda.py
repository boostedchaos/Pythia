"""openFDA drug enforcement reports (recalls), newest first.

Verified 2026-08-28: docs/feed-verification.md#openfda. Keyless tier is 240 requests
per minute and 1,000 per day per IP, which a half-hourly poll is far below.

openFDA records carry no public web page of their own, so the canonical url is a
query against the API for that recall_number — deterministic and resolvable.
"""
from __future__ import annotations

import json
from urllib.parse import quote

from ..models import Observation
from . import _util

SOURCE_ID = "openfda"
BEAT = "healthcare"
KIND = "stream"
DISPLAY_NAME = "openFDA drug enforcement reports"
CANONICAL_DOMAIN = "fda.gov"

URL = "https://api.fda.gov/drug/enforcement.json?sort=report_date%3Adesc&limit=25"

# %22 rather than a bare quote: a literal " is not valid in a URL.
_RECORD_URL = "https://api.fda.gov/drug/enforcement.json?search={field}:%22{value}%22"


def _title(row: dict) -> str:
    firm = _util.clean(row.get("recalling_firm"))
    product = _util.truncate(row.get("product_description"), 120)
    cls = _util.clean(row.get("classification"))
    head = " — ".join(p for p in (firm, product) if p)
    return f"{cls} recall: {head}" if cls else f"Recall: {head}"


def parse(payload: bytes) -> tuple[list[Observation], int]:
    data = json.loads(payload)
    results = data.get("results") or []
    out: list[Observation] = []
    for row in results:
        # Not every enforcement record carries a recall_number — a real Baxter
        # Class I recall on 2026-08-28 had only an event_id — so fall back rather
        # than dropping the item.
        recall_number = _util.clean(row.get("recall_number"))
        event_id = _util.clean(row.get("event_id"))
        if recall_number:
            field, value = "recall_number", recall_number
        elif event_id:
            field, value = "event_id", event_id
        else:
            continue
        title = _title(row)
        if not title.strip(" —:"):
            continue
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=_RECORD_URL.format(field=field, value=quote(value)),
                beat=BEAT,
                summary=_util.truncate(row.get("reason_for_recall")),
                upstream_id=value,
                source_ts_ms=_util.ms_from_date(row.get("report_date"), "%Y%m%d"),
                extra={
                    "doc_type": "enforcement_action",
                    "classification": _util.clean(row.get("classification")),
                    "status": _util.clean(row.get("status")),
                    "recalling_firm": _util.clean(row.get("recalling_firm")),
                    "voluntary_mandated": _util.clean(row.get("voluntary_mandated")),
                },
            )
        )
    return out, len(results)


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
