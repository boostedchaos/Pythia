"""PYTHIA Monitor — a private, always-on world-monitoring service.

Live global feeds are fused into a durable view of what is happening, what
CHANGED since last time, and which sources say so. One cheap LLM call turns
selected evidence into a cited brief.

Forecasting is retired: the experiment is archived under research mode
(PYTHIA_MODE=research) and its record lives in STATE.md and the ledger.
See PYTHIA-MONITOR-V1-PLAN.md.
"""
__version__ = "0.4.0"
