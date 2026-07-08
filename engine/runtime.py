"""Shared long-lived singletons."""
from __future__ import annotations

from .config import CONFIG
from .oracle import Oracle
from .osiris_intake import OsirisIntake
from .swarm import PERSONAS

intake = OsirisIntake()
oracle = Oracle()


def _persona_client(name: str) -> Oracle:
    """One DEDICATED client per swarm persona (never the shared oracle instance), so
    POST /model only ever moves the draft model — personas stay on their boot config."""
    model = CONFIG.swarm_models.get(name, CONFIG.llm_model)
    return Oracle(base=CONFIG.swarm_base_url, key=CONFIG.swarm_api_key, model=model)


# name -> the client that persona votes with
PERSONA_CLIENTS = {name: _persona_client(name) for name, _ in PERSONAS}
