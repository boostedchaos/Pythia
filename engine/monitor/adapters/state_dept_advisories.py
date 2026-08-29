"""US State Department travel advisories — official country risk advisories.

Verified 2026-08-28: docs/feed-verification.md#state_dept_advisories. Keyless;
US federal government work, public domain.

Adopted for the politics beat after ReliefWeb (needs a pre-approved appname) and
UN News (robots.txt) were both rejected — see the doc for the evidence on each.
Plan §8 asks for "humanitarian and official advisory sources"; this is the latter.

KIND is "snapshot", not "stream": the feed carries an advisory for every country
on every fetch (220 on 2026-08-28), so a country leaving the list is meaningful.

The advisory LEVEL is the operational signal — a country moving from Level 2 to
Level 4 is the change worth briefing — so it is parsed out of the title into
extra["advisory_level"] rather than left buried in prose.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..models import Observation
from . import _util

SOURCE_ID = "state_dept_advisories"
BEAT = "politics"
KIND = "snapshot"
DISPLAY_NAME = "US State Dept travel advisories"
CANONICAL_DOMAIN = "travel.state.gov"

URL = "https://travel.state.gov/_res/rss/TAsTWs.xml"

DC = "{http://purl.org/dc/elements/1.1/}"

# "Qatar - Level 3: Reconsider Travel"
_LEVEL = re.compile(r"Level\s+(\d)\s*:\s*(.+)$")
_TAG = re.compile(r"<[^>]+>")


def parse_level(title: str) -> tuple[int | None, str]:
    """-> (level, label). Returns (None, "") when the title does not carry one."""
    match = _LEVEL.search(title or "")
    if not match:
        return None, ""
    return int(match.group(1)), match.group(2).strip()


def _pubdate_ms(value: str | None) -> int | None:
    """This feed stamps dates with NO time ("Fri, 28 Aug 2026").

    email.utils.parsedate_to_datetime raises TypeError on that, so the date-only
    form is handled explicitly rather than by catching the crash.
    """
    if not value:
        return None
    text = value.strip()
    try:
        return int(parsedate_to_datetime(text).timestamp() * 1000)
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.strptime(text, "%a, %d %b %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _summary(description: str | None) -> str:
    """Descriptions are CDATA HTML; the brief wants prose."""
    if not description:
        return ""
    return _util.truncate(_TAG.sub(" ", description))


def parse(payload: bytes) -> tuple[list[Observation], int]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")
    out: list[Observation] = []
    for item in items:
        title = _util.clean(item.findtext("title"))
        url = _util.clean(item.findtext("link"))
        if not title or not url:
            continue
        level, label = parse_level(title)
        # "QA,advisory" — stable per country advisory, and better identity than the
        # url because the url stays constant while the advisory level changes.
        identifier = _util.clean(item.findtext(f"{DC}identifier")) or None
        country_code = identifier.split(",")[0] if identifier else ""
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                summary=_summary(item.findtext("description")),
                upstream_id=identifier,
                source_ts_ms=_pubdate_ms(item.findtext("pubDate")),
                extra={
                    "advisory_level": level,
                    "advisory_label": label,
                    "country_code": country_code,
                },
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
