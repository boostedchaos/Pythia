"""Shared monitor dataclasses. Contract: docs/phase-0.5-contract.md — do not drift."""
from __future__ import annotations

from dataclasses import dataclass, field

BEATS = ("ai", "cybersecurity", "politics", "healthcare", "markets")

# Adapter KIND values
STREAM = "stream"      # rolling feed; GONE is meaningless
SNAPSHOT = "snapshot"  # full current state each fetch; GONE is meaningful


@dataclass
class Observation:
    source_id: str
    title: str
    url: str
    beat: str
    summary: str = ""
    upstream_id: str | None = None
    source_ts_ms: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class AdapterRun:
    source_id: str
    status: str  # "healthy" | "empty" | "error"
    observations: "list[Observation]" = field(default_factory=list)
    http_status: int | None = None
    error: str | None = None
    received: int = 0
    accepted: int = 0
