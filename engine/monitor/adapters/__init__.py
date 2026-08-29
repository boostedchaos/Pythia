"""Adapter registry. Each module obeys docs/phase-0.5-contract.md.

Every source here was called for real before adoption; the evidence, the terms
verdict and the rejected candidates are in docs/feed-verification.md.

**Imports are ISOLATED per module (defect D1a, 2026-08-29).** This file used to do
one `from . import (a, b, c, ...)`, which is atomic: a syntax error in any single
adapter raised at package import, `_load_adapters()` caught it, and the registry went
13 -> 0 behind one WARNING line — while `/feeds/health` went on serving the stale
`sources` rows as `healthy`. One typo in one module silenced every feed and the
monitor reported itself green. Each module is now imported inside its own `try`, so a
broken one is a NAMED entry in `IMPORT_FAILURES` (which `collect` turns into a visible
errored source) and the other twelve keep collecting.

Modules are DISCOVERED from this directory rather than listed by hand, so adding an
adapter file is all it takes — there is no second place to forget. `_ORDER` only sets
the sequence briefs read in; anything not named there is still loaded, appended at the
end, and reported in `UNORDERED`.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

log = logging.getLogger("pythia.monitor.adapters")

# Brief-reading order, by beat. A name here that has no module file is reported in
# IMPORT_FAILURES like any other failure — a retired adapter must not vanish quietly.
_ORDER = (
    # ai
    "arxiv", "openai_news", "huggingface_blog",
    # cybersecurity
    "cisa_kev", "cisa_advisories",
    # politics
    "gdelt", "state_dept_advisories", "un_press",
    # healthcare
    "federal_register", "openfda",
    # markets
    "coingecko", "treasury_yields", "frankfurter",
)

# What every adapter module must expose (docs/phase-0.5-contract.md). A file that
# imports cleanly but does not meet this is NOT silently ignored — it is a failure,
# because a module that cannot be called is indistinguishable from one that is missing.
_REQUIRED = ("SOURCE_ID", "BEAT", "KIND", "fetch")


def discover_module_names() -> "list[str]":
    """Every adapter module in this directory, WITHOUT importing any of them.

    Reading the directory rather than a hand-kept list is what makes the count
    trustworthy: a module that fails to import still appears here, so the registry
    knows how many adapters it was supposed to have."""
    found = sorted(m.name for m in pkgutil.iter_modules([str(Path(__file__).parent)])
                   if not m.name.startswith("_"))
    ordered = [n for n in _ORDER if n in found]
    return ordered + [n for n in found if n not in _ORDER]


ADAPTERS: list = []
# (module_name, "ExcType: message") for every module that could not be registered.
IMPORT_FAILURES: "list[tuple[str, str]]" = []
# Module files present but missing from _ORDER — loaded, but their brief position is
# arbitrary until someone adds them to the tuple above.
UNORDERED: "list[str]" = []

_expected = set(_ORDER)
for _name in discover_module_names():
    if _name not in _expected:
        UNORDERED.append(_name)
    try:
        _module = importlib.import_module(f".{_name}", __name__)
        _missing = [a for a in _REQUIRED if not hasattr(_module, a)]
        if _missing:
            raise AttributeError("does not meet the adapter contract; missing "
                                 + ", ".join(_missing))
        ADAPTERS.append(_module)
    except Exception as _e:  # noqa: BLE001 — one bad module must not take the rest down
        IMPORT_FAILURES.append((_name, f"{type(_e).__name__}: {_e}"[:200]))
        log.error("adapter %s failed to import: %s: %s", _name, type(_e).__name__, _e)

for _name in _ORDER:
    if _name not in {m.__name__.rsplit(".", 1)[-1] for m in ADAPTERS} \
            and _name not in {n for n, _ in IMPORT_FAILURES}:
        IMPORT_FAILURES.append((_name, "FileNotFoundError: no such adapter module"))
        log.error("adapter %s is listed in _ORDER but has no module file", _name)

if UNORDERED:
    log.warning("adapter module(s) not listed in _ORDER, loaded at the end: %s",
                ", ".join(UNORDERED))

__all__ = ["ADAPTERS", "IMPORT_FAILURES", "UNORDERED", "discover_module_names"]
