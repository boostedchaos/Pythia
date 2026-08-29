"""GDELT DOC 2.0 API — recent English-language global politics coverage.

Verified 2026-08-28: docs/feed-verification.md#gdelt. Keyless. GDELT publishes its
data under CC0 1.0.

KNOWN LIVE ISSUE (2026-08-28): the wildcard certificate for *.gdeltproject.org
expired at 2026-08-28T19:50:12Z, so HTTPS requests fail TLS verification and this
adapter returns status="error". The API itself is healthy — the same query over
plain HTTP returned 200 with valid articles, and that response is the fixture. We
ship HTTPS deliberately rather than downgrading the transport; the adapter degrades
to "error" until the certificate is renewed. See docs/feed-verification.md#gdelt
for the recheck command.

GDELT articles carry no stable id, so identity falls back to the canonical url.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..models import Observation
from . import _util

SOURCE_ID = "gdelt"
BEAT = "politics"
KIND = "stream"
DISPLAY_NAME = "GDELT global news index"
CANONICAL_DOMAIN = "gdeltproject.org"

QUERY = (
    "(diplomacy OR sanctions OR ceasefire OR election OR treaty OR coup) sourcelang:eng"
)
URL = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query=(diplomacy%20OR%20sanctions%20OR%20ceasefire%20OR%20election%20OR%20treaty"
    "%20OR%20coup)%20sourcelang:eng"
    "&mode=artlist&maxrecords=50&format=json&sort=datedesc&timespan=1d"
)


def _seendate_ms(value: str | None) -> int | None:
    """GDELT stamps articles as 20260828T121500Z."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip(), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def parse(payload: bytes) -> tuple[list[Observation], int]:
    data = json.loads(payload)
    articles = data.get("articles") or []
    out: list[Observation] = []
    seen: set[str] = set()
    for row in articles:
        url = _util.clean(row.get("url"))
        title = _util.clean(row.get("title"))
        if not url or not title or url in seen:
            continue
        seen.add(url)
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                summary="",  # DOC 2.0 artlist returns no article body or snippet.
                upstream_id=None,  # No stable provider id; identity falls back to url.
                source_ts_ms=_seendate_ms(row.get("seendate")),
                extra={
                    "domain": _util.clean(row.get("domain")),
                    "source_country": _util.clean(row.get("sourcecountry")),
                    "language": _util.clean(row.get("language")),
                },
            )
        )
    return out, len(articles)


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
