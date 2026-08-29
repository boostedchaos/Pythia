"""OpenAI news RSS — vendor product/release announcements.

Verified 2026-08-28: docs/feed-verification.md#openai_news. Keyless public RSS.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import Observation
from . import _util

SOURCE_ID = "openai_news"
BEAT = "ai"
KIND = "stream"

URL = "https://openai.com/news/rss.xml"

# The feed is long (1157 items on 2026-08-28); a monitor only needs the head.
MAX_ITEMS = 30


def _rfc822_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value.strip()).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def parse(payload: bytes) -> tuple[list[Observation], int]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")
    out: list[Observation] = []
    for item in items[:MAX_ITEMS]:
        url = _util.clean(item.findtext("link"))
        title = _util.clean(item.findtext("title"))
        if not url or not title:
            continue
        guid = _util.clean(item.findtext("guid")) or None
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                summary=_util.truncate(item.findtext("description")),
                upstream_id=guid,
                source_ts_ms=_rfc822_ms(item.findtext("pubDate")),
                extra={"category": _util.clean(item.findtext("category"))} if item.findtext("category") else {},
            )
        )
    return out, len(items)


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
