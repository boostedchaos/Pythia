"""Shared adapter helpers. Contract: docs/phase-0.5-contract.md.

Adapters never raise. Every failure path returns an AdapterRun with status="error"
and a short, secret-free message.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..models import AdapterRun, Observation

# Contract: timeout <= 30s.
TIMEOUT = 25.0

# Identifies us politely to public APIs; carries no secret.
USER_AGENT = "PythiaMonitor/0.5 (+https://github.com/boostedchaos/Pythia)"
HEADERS = {"User-Agent": USER_AGENT}

_MAX_ERR = 200


def safe_error(exc: BaseException) -> str:
    """Exception -> short message safe to log. Never includes a URL query string."""
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"\?[^\s]*", "?<redacted>", text)
    return text[:_MAX_ERR]


def error_run(source_id: str, message: str, http_status: int | None = None) -> AdapterRun:
    return AdapterRun(
        source_id=source_id,
        status="error",
        observations=[],
        http_status=http_status,
        error=message[:_MAX_ERR],
    )


def finish(source_id: str, observations: list[Observation], received: int,
           http_status: int | None) -> AdapterRun:
    """Healthy when something was accepted, else empty."""
    return AdapterRun(
        source_id=source_id,
        status="healthy" if observations else "empty",
        observations=observations,
        http_status=http_status,
        received=received,
        accepted=len(observations),
    )


async def get(client, source_id: str, url: str, headers: dict | None = None):
    """GET returning (response, None) or (None, AdapterRun) on failure.

    Callers must return the AdapterRun unchanged when it is not None.
    """
    try:
        resp = await client.get(
            url, timeout=TIMEOUT, headers={**HEADERS, **(headers or {})}, follow_redirects=True
        )
    except Exception as exc:  # network, timeout, TLS — all become status="error"
        return None, error_run(source_id, safe_error(exc))
    if resp.status_code != 200:
        return None, error_run(source_id, f"HTTP {resp.status_code}", resp.status_code)
    return resp, None


def clean(text: str | None) -> str:
    """Collapse whitespace; RSS/Atom summaries arrive hard-wrapped."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def truncate(text: str, limit: int = 600) -> str:
    text = clean(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def ms_from_iso(value: str | None) -> int | None:
    """ISO-8601 (with Z or offset) -> ms since epoch. None when unparseable."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def ms_from_date(value: str | None, fmt: str = "%Y-%m-%d") -> int | None:
    """Date string in `fmt` -> ms since epoch at UTC midnight."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)
