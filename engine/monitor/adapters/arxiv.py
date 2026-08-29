"""arXiv API — recent cs.AI / cs.LG submissions.

Verified 2026-08-28: docs/feed-verification.md#arxiv. Keyless. arXiv's terms of use
ask for no more than one request every three seconds from a single connection.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..models import Observation
from . import _util

SOURCE_ID = "arxiv"
BEAT = "ai"
KIND = "stream"

URL = (
    "http://export.arxiv.org/api/query"
    "?search_query=cat:cs.AI+OR+cat:cs.LG"
    "&sortBy=submittedDate&sortOrder=descending&max_results=25"
)

ATOM = "{http://www.w3.org/2005/Atom}"


def _abs_url(entry: ET.Element) -> str:
    """Prefer the rel=alternate HTML link; fall back to <id>."""
    for link in entry.findall(f"{ATOM}link"):
        if link.get("rel") == "alternate" and link.get("href"):
            return link.get("href", "")
    return _util.clean(entry.findtext(f"{ATOM}id"))


def parse(payload: bytes) -> tuple[list[Observation], int]:
    root = ET.fromstring(payload)
    entries = root.findall(f"{ATOM}entry")
    out: list[Observation] = []
    for entry in entries:
        url = _abs_url(entry)
        title = _util.clean(entry.findtext(f"{ATOM}title"))
        if not url or not title:
            continue
        # arXiv ids carry a version suffix (2608.27454v1); the versionless id is the
        # stable identity, so a v2 revision is a change to the same paper, not a new one.
        raw_id = _util.clean(entry.findtext(f"{ATOM}id")).rsplit("/", 1)[-1]
        upstream_id = raw_id.split("v")[0] if raw_id else None
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                summary=_util.truncate(entry.findtext(f"{ATOM}summary")),
                upstream_id=upstream_id,
                source_ts_ms=_util.ms_from_iso(entry.findtext(f"{ATOM}published")
                                               or entry.findtext(f"{ATOM}updated")),
            )
        )
    return out, len(entries)


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
