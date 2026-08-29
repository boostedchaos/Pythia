"""Central configuration for the PYTHIA oracle (Osiris world data -> LLM -> predictions)."""
from __future__ import annotations

import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env", override=False)

# httpx defaults its CA bundle to certifi, which fails to load under some OpenSSL 3
# setups (X509: NO_CERTIFICATE_OR_CRL_FOUND) and 500s every request. The system
# trust store loads fine, so use it — this keeps full TLS verification on.
try:
    HTTPX_VERIFY: "ssl.SSLContext | bool" = ssl.create_default_context()
except Exception:  # noqa: BLE001 — fall back to httpx's default if the system store is unavailable
    HTTPX_VERIFY = True

# Reuse MiroFish's local LLM as the oracle's brain unless overridden in pythia/.env.
_MIROFISH_DIR = Path(os.environ.get("MIROFISH_DIR", str(Path.home() / "MiroFish")))


def _read_env_file(path: Path) -> dict:
    """Parse a foreign KEY=VALUE .env into a dict (missing file -> empty)."""
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


_MF = _read_env_file(_MIROFISH_DIR / ".env")
# The user's existing OpenRouter/API creds already live here — reuse them so the
# oracle needs no key of its own (mirrors the MiroFish .env reuse above).
_HERMES = _read_env_file(Path.home() / ".hermes" / ".env")

# OpenRouter wants attribution headers; harmless to any other OpenAI-compatible host.
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/jangles-byte/Pythia",
    "X-Title": "PYTHIA",
}

# Each swarm persona can run on its own model. name -> the env var that sets it.
_PERSONA_ENV = {
    "Strategist": "SWARM_STRATEGIST_MODEL",
    "Economist": "SWARM_ECONOMIST_MODEL",
    "Naturalist": "SWARM_NATURALIST_MODEL",
    "Skeptic": "SWARM_SKEPTIC_MODEL",
}


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _mode(name: str, default: str) -> str:
    """Operating mode, validated. An unknown value fails CLOSED to `monitor` —
    a typo must never silently re-enable forecasting."""
    v = os.environ.get(name, default).strip().lower()
    return v if v in ("monitor", "research") else "monitor"


@dataclass
class Config:
    root: Path = _ROOT
    runs_dir: Path = _ROOT / "runs"
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("PYTHIA_DATA_DIR", str(_ROOT / "runs"))))

    # ── Operating mode ──
    # monitor  = world-watching only. No forecast, swarm, ledger append, or resolver
    #            work happens AT ALL — excluded by construction, not by interval tuning.
    # research = the archived forecasting experiment, explicitly re-enabled.
    mode: str = field(default_factory=lambda: _mode("PYTHIA_MODE", "monitor"))

    osiris_url: str = field(default_factory=lambda: os.environ.get("OSIRIS_URL", "http://localhost:3000"))
    # Loopback by default: the engine holds provider credentials and has unauthenticated
    # mutating routes. A container deployment sets ENGINE_HOST=0.0.0.0 on a PRIVATE network.
    engine_host: str = field(default_factory=lambda: os.environ.get("ENGINE_HOST", "127.0.0.1"))
    engine_port: int = field(default_factory=lambda: _i("ENGINE_PORT", 8088))

    # ── API exposure ──
    # Explicit origins only; empty list = no cross-origin browser access.
    cors_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()])
    # Bearer token required on every route when set. Blank = open (loopback only).
    api_token: str = field(default_factory=lambda: os.environ.get("PYTHIA_API_TOKEN", "").strip())

    # ── Oracle LLM (defaults to MiroFish's configured local model) ──
    llm_base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL") or _MF.get("LLM_BASE_URL") or "http://localhost:11434/v1")
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY") or _MF.get("LLM_API_KEY") or "")
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL") or _MF.get("LLM_MODEL_NAME") or "llama3.1")
    temperature: float = field(default_factory=lambda: _f("ORACLE_TEMPERATURE", 0.5))
    request_timeout: int = field(default_factory=lambda: _i("ORACLE_TIMEOUT_SEC", 180))

    # ── Prediction behaviour ──
    horizons: list[str] = field(default_factory=lambda: [h.strip() for h in os.environ.get("HORIZONS", "24h,week,month,year").split(",") if h.strip()])
    predictions_per_horizon: int = field(default_factory=lambda: _i("PREDICTIONS_PER_HORIZON", 3))
    loop_interval_sec: int = field(default_factory=lambda: _i("LOOP_INTERVAL_SEC", 900))
    sense_interval_sec: int = field(default_factory=lambda: _i("SENSE_INTERVAL_SEC", 180))

    # ── Resolution / calibration (LLM judge scores forecasts on horizon expiry) ──
    judge_model: str = field(default_factory=lambda: os.environ.get("JUDGE_MODEL", ""))
    resolve_interval_sec: int = field(default_factory=lambda: _i("RESOLVE_INTERVAL_SEC", 1800))

    # ── Swarm (a council of LLM personas deliberates each forecast) ──
    swarm_enabled: bool = field(default_factory=lambda: _b("SWARM_ENABLED", True))
    # Each persona can run on its own model for genuinely decorrelated votes. The
    # backend defaults to the oracle's; per-persona model via SWARM_<NAME>_MODEL.
    swarm_base_url: str = field(default_factory=lambda: os.environ.get("SWARM_BASE_URL", ""))
    swarm_api_key: str = field(default_factory=lambda: os.environ.get("SWARM_API_KEY", ""))
    swarm_models: dict = field(default_factory=lambda: {
        n: os.environ[e] for n, e in _PERSONA_ENV.items() if os.environ.get(e)})

    def __post_init__(self) -> None:
        # Resolve the oracle key: explicit -> Hermes OpenRouter key (only when the
        # base IS OpenRouter, so a cloud key never leaks to a local host) -> Ollama dummy.
        if not self.llm_api_key:
            if "openrouter" in self.llm_base_url:
                self.llm_api_key = _HERMES.get("OPENROUTER_API_KEY") or ""
            self.llm_api_key = self.llm_api_key or "ollama"
        # Swarm backend inherits the oracle's unless overridden.
        self.swarm_base_url = self.swarm_base_url or self.llm_base_url
        if not self.swarm_api_key:
            self.swarm_api_key = self.llm_api_key
            if self.swarm_api_key == "ollama" and "openrouter" in self.swarm_base_url:
                self.swarm_api_key = _HERMES.get("OPENROUTER_API_KEY") or self.swarm_api_key
        # Any persona left unset uses the oracle model == today's single-model behaviour.
        for name in _PERSONA_ENV:
            self.swarm_models.setdefault(name, self.llm_model)
        # The resolution judge defaults to the (cheap) oracle draft model.
        self.judge_model = self.judge_model or self.llm_model

    @property
    def research_mode(self) -> bool:
        """True only when forecasting is EXPLICITLY enabled. Every forecast, swarm,
        ledger-append and resolver code path must be guarded on this."""
        return self.mode == "research"

    def summary(self) -> dict:
        """What this engine is actually doing. Forecast settings are omitted in
        monitor mode — advertising them implies work that never happens."""
        out = {
            "mode": self.mode,
            "osiris_url": self.osiris_url,
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "sense_interval_sec": self.sense_interval_sec,
        }
        if self.research_mode:
            out.update(swarm_models=self.swarm_models, horizons=self.horizons,
                       loop_interval_sec=self.loop_interval_sec)
        return out


CONFIG = Config()
CONFIG.runs_dir.mkdir(exist_ok=True)
