"""Assemble all Osiris feeds into one prose 'world brief' for the oracle."""
from __future__ import annotations

from collections import defaultdict

from .models import WorldBrief, WorldEvent

# One snapshot budget for everyone who reads the brief (oracle draft AND swarm personas).
BRIEF_CHARS = 6500


def build_brief(events: list[WorldEvent]) -> WorldBrief:
    by_cat: dict[str, list[WorldEvent]] = defaultdict(list)
    for e in events:
        by_cat[e.category].append(e)

    domains = {c: len(v) for c, v in by_cat.items()}
    lines: list[str] = []
    top: list[str] = []

    # most-active domains first
    for cat in sorted(by_cat, key=lambda c: -len(by_cat[c])):
        evs = sorted(by_cat[cat], key=lambda e: -e.salience)[:8]
        lines.append(f"\n[{cat.upper()}] ({len(by_cat[cat])} signals)")
        for e in evs:
            loc = f"  @{e.lat:.1f},{e.lng:.1f}" if e.lat is not None else ""
            extra = f" — {e.summary[:140]}" if e.summary else ""
            lines.append(f"  • {e.title}{extra}{loc}")
            top.append(e.title)

    text = "\n".join(lines).strip()
    return WorldBrief(
        event_count=len(events),
        domains=domains,
        text=text[:BRIEF_CHARS],
        top_events=top[:24],
    )
