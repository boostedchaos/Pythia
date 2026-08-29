"""Hugging Face blog RSS — the open-model half of the AI beat.

Verified 2026-08-28 and re-verified 2026-08-29: docs/feed-verification.md#huggingface_blog.
Keyless public RSS. Recorded as verified-but-held-in-reserve in Phase 0.5; adopted in
Phase 1 to deepen AI coverage beyond arXiv preprints and one vendor's announcements.

KNOWN LIMITATION, measured not assumed: **no item in this feed carries a <description>**
— 0 of 852 on 2026-08-29 — so every observation's summary is empty and the brief has only
the title to work with. That is a property of the source, so the adapter does not
manufacture a summary from anything else.

Two post families share the feed: official Hugging Face posts (/blog/<slug>) and
community/organisation posts (/blog/<org>/<slug>, 113 of 852). They are distinguished
structurally in extra["post_type"] rather than being filtered, since org posts from the
model labs are often the substantive ones.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import Observation
from . import _util

SOURCE_ID = "huggingface_blog"
BEAT = "ai"
KIND = "stream"
DISPLAY_NAME = "Hugging Face blog"
CANONICAL_DOMAIN = "huggingface.co"

URL = "https://huggingface.co/blog/feed.xml"

# The feed is a full archive (852 items on 2026-08-29); a monitor wants the head.
MAX_ITEMS = 30

_BLOG_ROOT = "https://huggingface.co/blog/"


def post_type(url: str) -> str:
    """Official posts are /blog/<slug>; community posts are /blog/<org>/<slug>."""
    if not url.startswith(_BLOG_ROOT):
        return "other"
    tail = url[len(_BLOG_ROOT):].strip("/")
    return "community" if "/" in tail else "official"


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
    out: list[Observation] = []
    seen: set[str] = set()
    for item in items[:MAX_ITEMS]:
        url = _util.clean(item.findtext("link"))
        title = _util.clean(item.findtext("title"))
        if not url or not title:
            continue
        if url in seen:
            continue
        seen.add(url)
        # guid equals link in every observed item, including the isPermaLink="false"
        # community posts, so it is a safe stable id rather than a second URL form.
        guid = _util.clean(item.findtext("guid")) or None
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                # This feed publishes no <description>; see the module docstring.
                summary=_util.truncate(item.findtext("description")),
                upstream_id=guid,
                source_ts_ms=_pubdate_ms(item.findtext("pubDate")),
                extra={"post_type": post_type(url)},
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
