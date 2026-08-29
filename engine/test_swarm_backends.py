"""Self-check for the multi-model swarm backend wiring. Pure, no network.

Run:  uv run python -m engine.test_swarm_backends   (or: pytest engine/test_swarm_backends.py)
"""
from __future__ import annotations

import os

from .config import OPENROUTER_HEADERS, _PERSONA_ENV, Config
from .oracle import Oracle

_SWARM_VARS = list(_PERSONA_ENV.values()) + ["SWARM_BASE_URL", "SWARM_API_KEY"]
_ORACLE_VARS = ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "OPENROUTER_API_KEY"]


def _clear(*names: str) -> None:
    for n in names:
        os.environ.pop(n, None)


def test_distinct_persona_models() -> None:
    """Per-persona env -> a distinct model for each persona, over one OpenRouter backend."""
    _clear(*_SWARM_VARS, *_ORACLE_VARS)
    os.environ.update({
        "LLM_BASE_URL": "https://openrouter.ai/api/v1",
        "LLM_API_KEY": "test-key",
        "LLM_MODEL": "deepseek/deepseek-v4-pro",
        "SWARM_STRATEGIST_MODEL": "anthropic/claude-sonnet-5",
        "SWARM_ECONOMIST_MODEL": "openai/gpt-5.5",
        "SWARM_NATURALIST_MODEL": "google/gemini-3.5-flash",
        "SWARM_SKEPTIC_MODEL": "deepseek/deepseek-v4-pro",
    })
    cfg = Config()
    assert cfg.swarm_base_url == "https://openrouter.ai/api/v1"
    assert cfg.swarm_api_key == "test-key"                       # inherits the oracle key
    assert cfg.swarm_models["Strategist"] == "anthropic/claude-sonnet-5"
    assert cfg.swarm_models["Economist"] == "openai/gpt-5.5"
    assert cfg.swarm_models["Naturalist"] == "google/gemini-3.5-flash"
    assert cfg.swarm_models["Skeptic"] == "deepseek/deepseek-v4-pro"
    assert len(set(cfg.swarm_models.values())) == 4              # four distinct models
    # build persona clients the way runtime does -> each votes with its own model
    clients = {n: Oracle(base=cfg.swarm_base_url, key=cfg.swarm_api_key, model=m)
               for n, m in cfg.swarm_models.items()}
    assert {c.model for c in clients.values()} == set(cfg.swarm_models.values())


def test_backward_compat_single_model() -> None:
    """No SWARM_* env -> every persona falls back to LLM_MODEL (today's behaviour)."""
    _clear(*_SWARM_VARS, *_ORACLE_VARS)
    os.environ.update({
        "LLM_BASE_URL": "http://localhost:11434/v1",
        "LLM_API_KEY": "ollama",
        "LLM_MODEL": "llama3.1",
    })
    cfg = Config()
    assert set(cfg.swarm_models.values()) == {"llama3.1"}
    assert cfg.swarm_base_url == "http://localhost:11434/v1"
    assert cfg.swarm_api_key == "ollama"


def test_oracle_headers() -> None:
    """OpenRouter base injects attribution headers; a local base does not."""
    o = Oracle(base="https://openrouter.ai/api/v1", key="k", model="m")
    h = o._headers()
    assert h["Authorization"] == "Bearer k"
    assert h.get("X-Title") == OPENROUTER_HEADERS["X-Title"]
    assert "X-Title" not in Oracle(base="http://localhost:11434/v1", key="ollama", model="x")._headers()


def main() -> None:
    test_distinct_persona_models()
    test_backward_compat_single_model()
    test_oracle_headers()
    _clear(*_SWARM_VARS, *_ORACLE_VARS)   # leave the environment clean
    print("ok — swarm backend wiring verified (3 checks passed)")


if __name__ == "__main__":
    main()
