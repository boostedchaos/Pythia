"""UN Meetings Coverage and Press Releases RSS — the politics beat's live source.

Verified 2026-08-29: docs/feed-verification.md#un_press. Keyless public RSS.

NOT the same host as `news.un.org`, which Phase 0.5 rejected on robots.txt. That
rejection turned on `Disallow: */news/` in the news.un.org rules; press.un.org publishes
its own robots.txt with a single `User-agent: *` group whose Disallow list covers only
admin, search and user paths. `/en/rss.xml` matches none of them. The evidence is
recorded in docs/feed-verification.md rather than inferred from the sibling host.

Identity is the UN DOCUMENT SYMBOL, not the url, because the feed publishes one meeting
under two urls: the press release (`/en/2026/sc16444.doc.htm`) and the live blog
(`/en/blog/sc16444`) both covered Security Council meeting sc16444 on 2026-08-29. Keying
on the url would put the same Council meeting in the brief twice; keying on the symbol
collapses them, preferring the press release as the authoritative record.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import Observation
from . import _util

SOURCE_ID = "un_press"
BEAT = "politics"
KIND = "stream"
DISPLAY_NAME = "UN press releases"
CANONICAL_DOMAIN = "press.un.org"

URL = "https://press.un.org/en/rss.xml"

# Document-symbol prefixes actually observed in the live feed on 2026-08-29. An
# unrecognised prefix is passed through in raw_prefix and typed "other" — never
# silently relabelled as something it is not.
_BODIES = {
    "sc": "security_council",
    "ga": "general_assembly",
    "sgsm": "sg_statement",
    "sga": "sg_appointment",
    "db": "daily_briefing",
    "bio": "biographical_note",
}

# Both url forms end in the document symbol: /en/<year>/<symbol>.doc.htm and /en/blog/<symbol>
_SYMBOL = re.compile(r"/(?:\d{4}|blog)/([a-z]+[\d/]+[a-z]?)(?:\.doc\.htm)?/?$", re.I)

_DOC_FORM = ".doc.htm"


def document_symbol(url: str) -> str | None:
    match = _SYMBOL.search(url)
    return match.group(1).lower() if match else None


def classify(symbol: str | None) -> tuple[str, str]:
    """Symbol -> (body, raw_prefix)."""
    if not symbol:
        return "other", ""
    prefix = re.match(r"[a-z]+", symbol)
    raw = prefix.group(0) if prefix else ""
    return _BODIES.get(raw, "other"), raw


def _pubdate_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value.strip()).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def parse(payload: bytes) -> tuple[list[Observation], int]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")

    by_key: dict[str, Observation] = {}
    order: list[str] = []
    for item in items:
        url = _util.clean(item.findtext("link"))
        title = _util.clean(item.findtext("title"))
        if not url or not title:
            continue
        symbol = document_symbol(url)
        body, raw_prefix = classify(symbol)
        key = symbol or url
        observation = Observation(
            source_id=SOURCE_ID,
            title=title,
            url=url,
            beat=BEAT,
            summary=_util.truncate(item.findtext("description")),
            upstream_id=symbol,
            source_ts_ms=_pubdate_ms(item.findtext("pubDate")),
            extra={"body": body, "raw_prefix": raw_prefix,
                   "document_symbol": symbol or ""},
        )
        held = by_key.get(key)
        if held is None:
            by_key[key] = observation
            order.append(key)
        elif _DOC_FORM in url and _DOC_FORM not in held.url:
            # Same meeting under two urls — keep the press release, not the live blog.
            by_key[key] = observation

    return [by_key[k] for k in order], len(items)


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
