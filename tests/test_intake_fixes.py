"""Regression tests for the intake defects found in the 2026-08-28 audit."""
from __future__ import annotations

import asyncio

import pytest

from engine.osiris_intake import OsirisIntake, _coord


# ── 5.5 coordinate-zero ──

@pytest.mark.parametrize("payload,expected", [
    ({"lat": 0, "lng": 0}, (0.0, 0.0)),                       # Null Island — the bug
    ({"lat": 0.0, "lng": 12.5}, (0.0, 12.5)),                 # equator
    ({"latitude": 51.5, "longitude": 0}, (51.5, 0.0)),        # prime meridian
    ({"lat": 48.5, "lng": 31.2}, (48.5, 31.2)),               # ordinary
    ({"geometry": {"coordinates": [0, 0]}}, (0.0, 0.0)),      # GeoJSON Null Island
    ({}, (None, None)),                                        # genuinely absent
    ({"lat": "abc", "lng": "def"}, (None, None)),             # unparseable
])
def test_coord_keeps_zero(payload, expected):
    assert _coord(payload) == expected


def test_coord_zero_is_not_dropped_by_truthiness():
    """Control: the OLD implementation returned (None, None) here. If this ever
    regresses, that is the `or`-chaining bug coming back."""
    assert _coord({"lat": 0, "lng": 0}) != (None, None)


# ── 5.9 one bad feed must not sink the others ──

class _Boom:
    """Stands in for a feed that raises something not in (HTTPError, ValueError)."""
    def __init__(self, blow_up_on: str):
        self.blow_up_on = blow_up_on

    async def get(self, url, timeout=None):
        if self.blow_up_on in url:
            raise KeyError("schema drift")
        raise RuntimeError("unreachable")


@pytest.mark.asyncio
async def test_one_exploding_feed_does_not_zero_the_rest(monkeypatch):
    intake = OsirisIntake(base_url="http://test.invalid")

    async def fake_fetch_feed(c, path, source, category):
        if source == "gdelt":
            raise KeyError("schema drift")
        return ([], {"source": source, "path": path, "status": "empty",
                     "error": None, "items_accepted": 0, "last_ok_at": None})

    monkeypatch.setattr(intake, "_fetch_feed", fake_fetch_feed)
    events, health = await intake.fetch_with_health(limit=10)

    assert health["gdelt"]["status"] == "error"
    assert "KeyError" in health["gdelt"]["error"]
    # the other 22 still reported — a single raise no longer cancels the gather
    assert len(health) == 23
    assert sum(1 for h in health.values() if h["status"] != "error") == 22


# ── 5.3 error vs healthy-empty must be distinguishable ──

@pytest.mark.asyncio
async def test_error_and_empty_are_different_states(monkeypatch):
    intake = OsirisIntake(base_url="http://test.invalid")

    async def fake_fetch_feed(c, path, source, category):
        if source == "news":
            return ([], {"source": source, "path": path, "status": "error",
                         "error": "HTTP 503", "items_accepted": 0, "last_ok_at": None})
        return ([], {"source": source, "path": path, "status": "empty",
                     "error": None, "items_accepted": 0, "last_ok_at": None})

    monkeypatch.setattr(intake, "_fetch_feed", fake_fetch_feed)
    _events, health = await intake.fetch_with_health(limit=10)

    # Both produced zero events. Only one of them is a problem.
    assert health["news"]["status"] == "error"
    assert health["usgs"]["status"] == "empty"
    assert health["news"]["status"] != health["usgs"]["status"]
