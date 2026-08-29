"""Federal Register API — HHS / CMS / FDA documents.

Verified 2026-08-28: docs/feed-verification.md#federal_register. Keyless; US federal
government work, public domain.

The classification the plan asks for (§8) is carried in extra["doc_type"]: the API's
own `type` field, normalised to proposed_rule / final_rule / notice / presidential.
"""
from __future__ import annotations

import json

from ..models import Observation
from . import _util

SOURCE_ID = "federal_register"
BEAT = "healthcare"
KIND = "stream"

AGENCIES = (
    "health-and-human-services-department",
    "centers-for-medicare-medicaid-services",
    "food-and-drug-administration",
)
FIELDS = (
    "document_number", "title", "type", "html_url",
    "publication_date", "abstract", "agencies", "action",
)
URL = (
    "https://www.federalregister.gov/api/v1/documents.json?per_page=40&order=newest"
    + "".join(f"&conditions%5Bagencies%5D%5B%5D={a}" for a in AGENCIES)
    + "".join(f"&fields%5B%5D={f}" for f in FIELDS)
)

# The API's `type` values, mapped to the plan's vocabulary. Anything unrecognised
# is passed through lowercased rather than silently dropped into "notice".
DOC_TYPES = {
    "Proposed Rule": "proposed_rule",
    "Rule": "final_rule",
    "Notice": "notice",
    "Presidential Document": "presidential",
}


def classify(raw_type: str | None) -> str:
    if not raw_type:
        return "unknown"
    return DOC_TYPES.get(raw_type.strip(), raw_type.strip().lower().replace(" ", "_"))


def parse(payload: bytes) -> tuple[list[Observation], int]:
    data = json.loads(payload)
    results = data.get("results") or []
    out: list[Observation] = []
    for row in results:
        url = _util.clean(row.get("html_url"))
        title = _util.clean(row.get("title"))
        if not url or not title:
            continue
        agencies = [
            _util.clean(a.get("name"))
            for a in (row.get("agencies") or [])
            if a.get("name")
        ]
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                summary=_util.truncate(row.get("abstract") or row.get("action")),
                upstream_id=_util.clean(row.get("document_number")) or None,
                source_ts_ms=_util.ms_from_date(row.get("publication_date")),
                extra={
                    "doc_type": classify(row.get("type")),
                    "raw_type": _util.clean(row.get("type")),
                    "action": _util.clean(row.get("action")),
                    "agencies": agencies,
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
