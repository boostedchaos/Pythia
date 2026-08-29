"""CISA advisories RSS — the analyst-written half of the cybersecurity beat.

Verified 2026-08-29: docs/feed-verification.md#cisa_advisories. Keyless public RSS,
US federal government work.

Complements `cisa_kev`, it does not duplicate it. KEV is a machine-readable catalog of
CVEs confirmed exploited; this feed is CISA's written output — ICS advisories, AA-series
joint advisories, and alerts. Nine of the thirty items on 2026-08-29 were "CISA Adds N
Known Exploited Vulnerabilities to Catalog" alerts, which DO restate KEV activity. They
are kept rather than filtered — dropping them would need a title-sniffing rule that
would eventually swallow a real alert — and are classified via extra["advisory_type"]
so a consumer can tell them apart structurally.

The advisory URL is stable across revisions: an advisory reissued as "(Update D)" keeps
its id and its link, so a revision is a CHANGE to the same observation rather than a new
one. That is why identity comes from the advisory id, never from the title.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import Observation
from . import _util

SOURCE_ID = "cisa_advisories"
BEAT = "cybersecurity"
KIND = "stream"
DISPLAY_NAME = "CISA advisories"
CANONICAL_DOMAIN = "cisa.gov"

URL = "https://www.cisa.gov/cybersecurity-advisories/all.xml"

# URL path segment -> advisory type. Structural, so it cannot be fooled by wording.
_TYPES = {
    "ics-advisories": "ics_advisory",
    "cybersecurity-advisories": "joint_advisory",
    "alerts": "alert",
}

# Advisory ids live in the last path segment of the two advisory sections, e.g.
# ".../ics-advisories/icsa-26-239-03" and ".../cybersecurity-advisories/aa26-237a".
# Alert URLs are dated slugs with no such id, so they fall back to url identity.
_ID_SECTIONS = ("ics-advisories", "cybersecurity-advisories")


def classify(url: str) -> tuple[str, str]:
    """URL -> (advisory_type, raw_section). Unknown sections pass through, never relabelled."""
    parts = [p for p in url.split("/") if p]
    section = ""
    for part in parts:
        if part in _TYPES or part in ("resources-tools", "resources"):
            section = part
            break
    return _TYPES.get(section, "other"), section


def advisory_id(url: str) -> str | None:
    parts = [p for p in url.rstrip("/").split("/") if p]
    for section in _ID_SECTIONS:
        if section in parts:
            index = parts.index(section)
            if index + 1 < len(parts):
                return parts[index + 1]
    return None


def _pubdate_ms(value: str | None) -> int | None:
    """RFC-822. This feed stamps a TWO-DIGIT year ('Thu, 27 Aug 26 12:00:00 +0000').

    email.utils reads that per RFC 2822 (00-49 -> 2000s), so 26 -> 2026. Checked
    against every distinct pubDate in the live feed; guarded by a test, because a
    regression here would shift every timestamp by ~2000 years silently.
    """
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value.strip()).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _strip_html(text: str | None) -> str:
    """Descriptions are escaped HTML (tables and all); the brief wants prose."""
    return _util.truncate(re.sub(r"<[^>]+>", " ", text or ""))


def parse(payload: bytes) -> tuple[list[Observation], int]:
    root = ET.fromstring(payload)
    items = root.findall("./channel/item")
    out: list[Observation] = []
    seen: set[str] = set()
    for item in items:
        url = _util.clean(item.findtext("link"))
        title = _util.clean(item.findtext("title"))
        if not url or not title:
            continue
        advisory_type, section = classify(url)
        upstream = advisory_id(url)
        key = upstream or url
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=title,
                url=url,
                beat=BEAT,
                summary=_strip_html(item.findtext("description")),
                upstream_id=upstream,
                source_ts_ms=_pubdate_ms(item.findtext("pubDate")),
                extra={"advisory_type": advisory_type, "raw_section": section},
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
