# PYTHIA — project instructions (this fork)

PYTHIA is a local world-watching prediction oracle: it fuses ~23 keyless live global feeds (served
by an Osiris checkout) → an LLM → concrete, located forecasts across 24h/week/month/year, has a
persona **swarm** deliberate each one, and exposes the whole world-view as an agent API on `:8088`.
Upstream: github.com/jangles-byte/Pythia (built on MiroFish + Osiris).

**This fork's headline change:** the 4-persona swarm (Strategist/Economist/Naturalist/Skeptic) runs
each persona on a **different model over OpenRouter**, so votes genuinely decorrelate. The full
themed Osiris web UI is also rolled out (into `osiris-live/` in this repo, its own git checkout) — oracle deck,
swarm deliberation, chat, 9 social map layers, light/dark theme — plus a keyless engine dashboard
at `GET /` on `:8088`.

## Working here

- `origin` points at UPSTREAM (jangles-byte). **Fork before pushing.** Don't commit unless asked.
- **Record of record = `STATE.md`** (status + dated decisions). Read it before changing things.
- Durable cross-session knowledge = `~/.claude/memory/domain/pythia.md`.
- Approved design = `~/.claude/plans/typed-herding-melody.md`.

## Layout

- `engine/` — FastAPI oracle (~1k LOC). Flow: `osiris_intake` (fuse feeds) → `world_state` (prose
  brief) → `oracle` (draft predictions) → `swarm` (per-persona deliberation) → `server`
  (API + SSE + `/` dashboard). `runtime` holds the singletons + `PERSONA_CLIENTS`.
- `engine/dashboard.html` — self-contained SSE live view (this fork), served at `GET /`.
- `engine/test_swarm_backends.py` — pure self-check. Run: `uv run python -m engine.test_swarm_backends`.
- `osiris-live/` — the live Osiris checkout (stock `simplifaisoul/osiris` clone + overlay applied).
  **Nested git repo**, gitignored by Pythia — moved here 2026-07-02 from `~/Documents/PROJECTS/osiris-live`.
- `integrations/osiris/` — TS/React overlay (globe UI + keyless feed routes). **Applied** to
  `osiris-live/`: 8 components + engine-proxy
  - keyless routes copied in; `page.tsx`/`OsirisMap.tsx`/`LayerPanel.tsx`/`globals.css`/`layout.tsx`
  edited additively (PYTHIA deck/chat/credits/ticker, `.pythia-scope` readable colors, Doto font,
  9 social circle layers mirroring the earthquake feed, `body.theme-light` + Positron light basemap).

## Run the live stack (verified 2026-07-02)

Needs a running Osiris (for feeds) + OpenRouter creds. **:3000 is taken by the separate
`~/mission-control` app** (its /api routes 401 and silently starve the engine) — run on **:3001**:

1. `cd ~/Documents/PROJECTS/Pythia/osiris-live && PORT=3001 npm run dev`     # :3001, real feeds
2. `cd ~/Documents/PROJECTS/Pythia && OSIRIS_URL=http://localhost:3001 uv run python -m engine.run`  # :8088
3. Open **<http://localhost:3001>** — the full themed PYTHIA globe UI (deck, deliberation, chat,
   ORACLE + SOCIAL layer groups, prediction markers, Sun/Moon theme toggle). The engine's own
   minimal dashboard is at <http://localhost:8088/>. `?layers=<keys>` presets active map layers.

**Verifying the UI:** the Chrome extension may be disconnected — use the **Playwright MCP**
(`browser_navigate` → `browser_console_messages` → `browser_take_screenshot`) to load `:3001`,
confirm the globe renders, and screenshot. Osiris throws 2 pre-existing CoinGecko-CORS console
errors that are NOT ours.

`.env` is OpenRouter multi-model. `LLM_API_KEY` blank → auto-reads `OPENROUTER_API_KEY` from
`~/.hermes/.env` (no secret in-repo). Persona→model: Strategist=`anthropic/claude-sonnet-5`,
Economist=`openai/gpt-5.4-mini`, Naturalist=`google/gemini-3.5-flash`, Skeptic + oracle
draft=`deepseek/deepseek-v4-pro`. Override per persona via `SWARM_<NAME>_MODEL`; unset → falls back
to `LLM_MODEL` (single-model = upstream behaviour, backward compatible).

**Cost:** ~$0.06 per forecast pass (measured). Auto-loop at `LOOP_INTERVAL_SEC=1800` (30 min) ≈
$0.10–0.13/hr; ~$0 idle (feed refresh makes no LLM calls). Economist is `gpt-5.4-mini` because
`gpt-5.5` was ~half the whole pass cost. Cheapen further: `openai/gpt-5-mini`, longer interval, or
`PREDICTIONS_PER_HORIZON=2`.

## Calibration (shipped 2026-07-02)

Every pass persists to `runs/predictions.jsonl` (`engine/ledger.py`); `engine/resolver.py` runs a
batched LLM judge on expired forecasts (rides the sense loop every `RESOLVE_INTERVAL_SEC`, or
`POST /resolve`) → `runs/resolutions.jsonl` → Brier track record (overall / vs-draft / per-horizon /
**per-persona**) at `GET /history` + SSE `kind="track"` + a dashboard strip. `unresolvable` is
terminal. Judge = `JUDGE_MODEL` (blank → `LLM_MODEL`). Self-check: `uv run python -m engine.test_ledger`.

## Gotchas

- OpenRouter **reasoning models** (DeepSeek, Gemini Flash) spend completion tokens on hidden
  reasoning before any content, so a too-small `max_tokens` returns `content: null`.
  `oracle._complete` null-guards it; budgets were raised (draft 4000 / swarm 3000 / chat 2000).
  Verify model slugs against `curl -s https://openrouter.ai/api/v1/models`.
- **Never `git stash` in `osiris-live`** — the overlay's edits to the 6 tracked files exist only in
  that worktree (recoverable copy: `integrations/osiris/tracked-edits.patch`). If the worktree is
  ever reverted/restored while `next dev` runs, delete `.next` — Turbopack serves stale CSS chunks.
- `POST /model` switches the **draft oracle only**; personas are pinned at boot (dedicated clients).
- UI theming: swap body theme classes with `classList`, never `body.className =` (it wipes
  `theme-switching`/`antialiased`). Light-mode text tokens are WCAG-AA computed; stock hardcoded
  hexes are overridden via `body.theme-light [class*="<hex>"]` in `globals.css`; the black bottom
  bars pin the dark text palette locally. Deck height is coupled to the button cluster
  (`max-h min(82vh, 100dvh−440px)`) — if the cluster moves/grows, retune. If the UI looks
  broken-stacked after a `.next` swap, it's the browser's stale CSS chunk — hard refresh (⌘⇧R).

## Deferred

Let the track record accumulate (auto-loop on for a few days → real Brier numbers), then optionally
surface `track_record` in the osiris-live deck. Details in `STATE.md`.
