# Phase 0.5 build contract (architect-issued, 2026-08-28)

Both build lanes follow this exactly. If a lane must deviate, it records the deviation
in its report; it does not renegotiate the interface unilaterally.

## Package layout

New code lives in `engine/monitor/`:

- `models.py` — shared dataclasses (Lane S owns the file; Lane F imports it)
- `store.py`, `delta.py`, `brief.py`, `schedule.py`, `ntfy.py` — Lane S
- `adapters/__init__.py` (registry) + `adapters/<source>.py` — Lane F

## Shared dataclasses (in `engine/monitor/models.py`)

```python
BEATS = ("ai", "cybersecurity", "politics", "healthcare", "markets")

@dataclass
class Observation:
    source_id: str          # adapter's SOURCE_ID
    title: str
    url: str                # canonical link; required
    beat: str               # one of BEATS
    summary: str = ""
    upstream_id: str | None = None   # provider's own stable id if it has one
    source_ts_ms: int | None = None  # provider's own timestamp, ms epoch
    extra: dict = field(default_factory=dict)  # e.g. {"price": 123.4} for markets

@dataclass
class AdapterRun:
    source_id: str
    status: str             # "healthy" | "empty" | "error"
    observations: list[Observation]
    http_status: int | None = None
    error: str | None = None          # safe summary, no secrets
    received: int = 0                 # items seen in the payload
    accepted: int = 0                 # items that became Observations
```

## Adapter module contract (Lane F)

Each `engine/monitor/adapters/<name>.py` exposes:

- `SOURCE_ID: str` — stable, lowercase, e.g. `"federal_register"`
- `BEAT: str` — one of BEATS
- `KIND: str` — `"stream"` (rolling feed; GONE is meaningless) or
  `"snapshot"` (full current state each fetch; GONE is meaningful, e.g. CISA KEV,
  a market instrument list)
- `async def fetch(client: httpx.AsyncClient) -> AdapterRun` — never raises; all
  failure becomes `status="error"` with a safe error string. Timeout ≤ 30s.

`adapters/__init__.py` exports `ADAPTERS: list[module]`.

## Identity (Lane S implements; Lane F must supply the inputs)

`obs_id = sha256(f"{source_id}|{natural_key}").hexdigest()[:24]` where
`natural_key = upstream_id or canonical_url or normalized_title` (first non-empty).
Market instruments: `upstream_id = the symbol` (e.g. `"BTC"`), price goes in
`extra["price"]` — the price must NEVER be part of identity (plan §5.11).

## Env contract (container-first; no file reads outside the repo)

- `OPENROUTER_API_KEY` (required for the LLM step), `LLM_BASE_URL`
  (default `https://openrouter.ai/api/v1`), `BRIEF_MODEL`
- `NTFY_URL` (default `https://ntfy.sh`), `NTFY_TOPIC` (secret, VM .env only)
- `BRIEF_HOUR_LOCAL` (default `7`), `BRIEF_TZ` (default `America/Chicago`)
- `PYTHIA_LLM_MONTHLY_CAP_USD` (default `5`)
- Reads of `~/.hermes/.env` and MiroFish `.env` are REMOVED (plan §5.12).

## Hard rules for both lanes

- No LLM anywhere in fetch/normalize/delta. One LLM call per brief, rewrite-only.
- Never commit, never push, never touch any host except 192.168.0.28.
- No secret in repo, image, or any log/print. No `~/.hermes` reads.
- Every test that guards a fix must be shown to FAIL when the fix is reverted.
