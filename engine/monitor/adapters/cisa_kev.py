"""CISA Known Exploited Vulnerabilities catalog.

Verified 2026-08-28: docs/feed-verification.md#cisa_kev. Keyless; US federal
government work, public domain.

KIND is "snapshot": every fetch returns the whole catalog, so a CVE disappearing
from it is meaningful. KEV rows carry no link of their own, so the canonical url is
the NVD detail page for the CVE — deterministic from the id.
"""
from __future__ import annotations

import json

from ..models import Observation
from . import _util

SOURCE_ID = "cisa_kev"
BEAT = "cybersecurity"
KIND = "snapshot"
DISPLAY_NAME = "CISA Known Exploited Vulnerabilities catalog"
CANONICAL_DOMAIN = "cisa.gov"

URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

_NVD_URL = "https://nvd.nist.gov/vuln/detail/{}"


def parse(payload: bytes) -> tuple[list[Observation], int]:
    data = json.loads(payload)
    vulns = data.get("vulnerabilities") or []
    catalog_version = _util.clean(data.get("catalogVersion"))
    out: list[Observation] = []
    for row in vulns:
        cve = _util.clean(row.get("cveID"))
        if not cve:
            continue
        vendor = _util.clean(row.get("vendorProject"))
        product = _util.clean(row.get("product"))
        name = _util.clean(row.get("vulnerabilityName")) or cve
        title = f"{cve}: {vendor} {product} — {name}".replace("  ", " ")
        ransomware = _util.clean(row.get("knownRansomwareCampaignUse"))
        out.append(
            Observation(
                source_id=SOURCE_ID,
                title=_util.clean(title),
                url=_NVD_URL.format(cve),
                beat=BEAT,
                summary=_util.truncate(row.get("shortDescription")),
                upstream_id=cve,
                source_ts_ms=_util.ms_from_date(row.get("dateAdded")),
                extra={
                    "vendor_project": vendor,
                    "product": product,
                    "date_added": _util.clean(row.get("dateAdded")),
                    "due_date": _util.clean(row.get("dueDate")),
                    "known_ransomware_use": ransomware,
                    "cwes": row.get("cwes") or [],
                    "catalog_version": catalog_version,
                },
            )
        )
    return out, len(vulns)


async def fetch(client):
    resp, failure = await _util.get(client, SOURCE_ID, URL)
    if failure is not None:
        return failure
    try:
        observations, received = parse(resp.content)
    except Exception as exc:
        return _util.error_run(SOURCE_ID, _util.safe_error(exc), resp.status_code)
    return _util.finish(SOURCE_ID, observations, received, resp.status_code)
