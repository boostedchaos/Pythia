"""ntfy push for the published brief.

The topic is the credential: anyone who knows it can read the pushes. It is never
logged, never returned in an API response, and never included in an error string.
"""
from __future__ import annotations

import logging
import re
import unicodedata

import httpx

from ..config import CONFIG, HTTPX_VERIFY

log = logging.getLogger("pythia.monitor.ntfy")

MAX_BODY_CHARS = 900
MAX_TITLE_CHARS = 200
PREVIEW_BULLETS = 5

# httpx encodes header values as ASCII (httpx/_models.py:82,
# `value.encode(encoding or "ascii")`) — not latin-1. A brief title carrying an em
# dash therefore raised UnicodeEncodeError before the request was ever sent, which
# is how the first real brief published correctly and delivered nothing.
# The BODY is passed as UTF-8 bytes and is unaffected; only headers need folding.
_FOLD = {
    "—": "-", "–": "-", "−": "-",     # em/en dash, minus
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "→": "->", "←": "<-", "…": "...",
    "•": "*", "⚠": "!", " ": " ",
}


def ascii_header(value: str) -> str:
    """Fold a header value to plain ASCII on one line.

    Typographic characters get a readable equivalent; accents decompose (café ->
    cafe); anything left over (emoji, CJK) is dropped rather than crashing the
    request. Control characters go too — a newline in a header value is header
    injection, not a formatting problem."""
    folded = "".join(_FOLD.get(ch, ch) for ch in value)
    folded = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode("ascii")
    return " ".join(folded.split())


def _summarise(result: dict) -> "tuple[str, str]":
    """(title, body). Per-beat counts plus the first few bullet lines."""
    markdown = result.get("markdown") or ""
    lines = [ln.strip() for ln in markdown.splitlines()]
    per_beat: dict[str, int] = {}
    beat = ""
    bullets: list[str] = []
    for ln in lines:
        if ln.startswith("## "):
            beat = ln[3:].strip()
            per_beat.setdefault(beat, 0)
        elif ln.startswith("- "):
            per_beat[beat] = per_beat.get(beat, 0) + 1
            if len(bullets) < PREVIEW_BULLETS:
                # strip the markdown citation links; the push is plain text
                bullets.append(re.sub(r"\s*\[[^\]]*\]\([^)]*\)", "", ln[2:]).strip())

    total = sum(per_beat.values())
    label = "PYTHIA brief" if result.get("status") == "published" else "PYTHIA brief (deterministic)"
    title = f"{label} {result.get('brief_date', '')} — {total} item(s)"
    counts = ", ".join(f"{b}: {n}" for b, n in per_beat.items() if n) or "no changes"
    parts = [counts, ""]
    parts += [f"• {b}" for b in bullets]
    if total > len(bullets):
        parts.append(f"…and {total - len(bullets)} more.")
    if result.get("coverage_warnings"):
        parts.append("⚠ coverage gap: " + ", ".join(sorted(result["coverage_warnings"])))
    return title, "\n".join(parts)[:MAX_BODY_CHARS]


async def send_brief(result: dict, timeout: int = 20,
                     transport: "httpx.AsyncBaseTransport | None" = None) -> dict:
    """POST the brief summary. Returns a delivery record; never raises upward.

    `transport` exists so a test can drive the REAL httpx request path — including
    its header encoding, which is where this used to fail — without a network."""
    if not CONFIG.ntfy_topic:
        return {"sent": False, "reason": "NTFY_TOPIC not configured"}
    title, body = _summarise(result)
    # Every header value is folded, not just the one known to have broken: the next
    # header added here must not be able to reintroduce the same failure.
    headers = {k: ascii_header(v) for k, v in
               {"Title": title[:MAX_TITLE_CHARS], "Tags": "newspaper"}.items()}
    try:
        kwargs = {"verify": HTTPX_VERIFY} if transport is None else {"transport": transport}
        async with httpx.AsyncClient(timeout=timeout, **kwargs) as c:
            r = await c.post(f"{CONFIG.ntfy_url}/{CONFIG.ntfy_topic}",
                             content=body.encode("utf-8"), headers=headers)
        ok = r.status_code < 400
        if not ok:
            # Status only — the URL carries the topic, so it is not logged.
            log.warning("ntfy rejected the brief: HTTP %s", r.status_code)
        return {"sent": ok, "http_status": r.status_code}
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy delivery failed: %s", type(e).__name__)
        return {"sent": False, "error": type(e).__name__}


def _warnings_from_markdown(markdown: str) -> "list[str]":
    """Recover the coverage-warning source names from a stored brief, so a resend
    says the same thing the original push would have."""
    for line in markdown.splitlines():
        if "Coverage warning" in line:
            return re.findall(r"`([^`]+)`", line)
    return []


async def resend_latest(store=None) -> dict:
    """Re-deliver the notification for the LATEST stored brief.

    Reads the brief already in the database: no LLM call, no collection, no new
    brief row. Use it to prove delivery end to end after a delivery-only failure."""
    from .store import get_store
    store = store or get_store()
    row = store.latest_brief()
    if not row:
        return {"sent": False, "reason": "no published brief to resend"}
    result = {"status": row["status"], "brief_date": row["brief_date"],
              "markdown": row["markdown"] or "",
              "coverage_warnings": _warnings_from_markdown(row["markdown"] or "")}
    delivery = await send_brief(result)
    return {"brief_date": row["brief_date"], "status": row["status"], **delivery}


if __name__ == "__main__":
    import asyncio
    import json
    print(json.dumps(asyncio.run(resend_latest())))
