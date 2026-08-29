# PYTHIA — project instructions (this fork)

> **2026-08-28: this is PYTHIA Monitor now, not a forecasting oracle.** Read
> **`PYTHIA-MONITOR-V1-PLAN.md` first** — it is the plan of record (decisions, phases, acceptance
> gates). Everything below the "Mode" heading describes the pre-pivot build and is kept as
> history; where it conflicts with the plan, the plan wins.

PYTHIA Monitor is a private, always-on world-monitoring service: it collects live feeds across
five beats (AI, cybersecurity, global politics, US healthcare regulation, markets), tracks what
**changed**, and writes a cited daily brief. It exposes the same evidence to other agents on
`:8088`. Forecasting is retired and archived behind `PYTHIA_MODE=research`.

Upstream: github.com/jangles-byte/Pythia (built on MiroFish + Osiris) — diverged; do not merge.

## Working here

- **`origin` is `github.com/boostedchaos/Pythia` — Kyle's own fork.** (This line said "origin
  points at UPSTREAM, fork before pushing" until 2026-08-28; that was wrong.) Upstream is not
  configured as a remote. Don't commit unless asked, and don't push without asking.
- **Active branch = `main`** (was `monitor-v1`; renamed and made the GitHub default 2026-08-29).
  `review-fixes` is the forecasting experiment's archive — do not rewrite it.
- **Plan of record = `PYTHIA-MONITOR-V1-PLAN.md`.** Status log = `STATE.md` (newest dated entry at
  top is truth; the `## Status` bullets below it are pre-pivot history).
- `BUILD-PROMPT.md` = paste-ready prompt to build the remaining phases autonomously.
- Durable cross-session knowledge = `~/.claude/memory/domain/pythia.md`.
- **Deployed on VM 107 `pythia`, Proxmox node pve2, `192.168.0.28`** —
  `ssh -i ~/.ssh/id_ed25519_pythia pythia@192.168.0.28`; stack at `~/pythia/deploy/compose`.
  Nightly `vzdump` job `pythia-daily` at 03:00. Deploy/health/restore commands: plan §13.
- Pre-pivot design doc (historical) = `~/.claude/plans/typed-herding-melody.md`.

## Mode (pre-pivot sections follow — history, not instructions)

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
`~/.hermes/.env` (no secret in-repo). Persona→model (retuned 2026-07-04 for cost, same OpenRouter
pricing check that picked these): Strategist=`x-ai/grok-4.3`, Economist=`openai/gpt-5-mini`,
Naturalist=`google/gemini-3.1-flash-lite`, Skeptic + oracle draft=`deepseek/deepseek-v4-pro`
(unchanged — already the cheap anchor). Override per persona via `SWARM_<NAME>_MODEL`; unset →
falls back to `LLM_MODEL` (single-model = upstream behaviour, backward compatible).

**Cost:** was ~$0.06/pass (previously Strategist=`claude-sonnet-5`, Economist=`gpt-5.4-mini`,
Naturalist=`gemini-3.5-flash`); the 2026-07-04 retune targets a ~70% cut on the swarm-deliberation
portion (same-or-cheaper completion-token pricing on all 3 swapped personas — see STATE.md Cost
table for per-call pricing and the rationale). Not yet re-measured live — **check `GET /history`
after this runs a few days**: the swap is a same-tier-down bet (Grok/gpt-5-mini/flash-lite vs their
pricier siblings), not benchmark-verified for this task, so the per-persona Brier track record is
the real check on whether it held up. Auto-loop at `LOOP_INTERVAL_SEC=1800` (30 min). Cheapen
further: longer interval, or `PREDICTIONS_PER_HORIZON=2`.

## Calibration (shipped 2026-07-02)

Every pass persists to `runs/predictions.jsonl` (`engine/ledger.py`); `engine/resolver.py` runs a
batched LLM judge on expired forecasts (rides the sense loop every `RESOLVE_INTERVAL_SEC`, or
`POST /resolve`) → `runs/resolutions.jsonl` → Brier track record (overall / vs-draft / per-horizon /
**per-persona**) at `GET /history` + SSE `kind="track"` + a dashboard strip. `unresolvable` is
terminal. Judge = `JUDGE_MODEL` (blank → `LLM_MODEL`). Self-check: `uv run python -m engine.test_ledger`.

**Read Brier against the base rate, not against 0.25.** Events here are rare (~7% true), so the
honest benchmark is "always predict the base rate" (Brier ~0.064), NOT a 50/50 coin flip (0.25).
The 2026-07-05 review found the system badly **over-forecasting**: consensus Brier 0.249 only looked
OK next to the wildly overconfident raw draft (0.579) — it's ~4× worse than the trivial 0.064 bar.
`track_record()` now also returns `brier_baserate` + `base_rate` and the dashboard shows a
`base-rate ✓/⚠` chip. Fixes shipped the same day: (1) `oracle.py` SYSTEM + `swarm.py` persona
prompts carry **calibration** (low base rates; P% must mean ~P%; reserve >60% for in-progress /
confirmed-trigger events) + **verifiability** (predict observable events a later snapshot can
confirm, not private meeting outcomes) discipline; (2) `ledger.append_predictions()` **dedups**
near-duplicates (word-Jaccard ≥0.6) of a still-active same-horizon forecast so one running story
(Doha talks were 104 rows) doesn't dominate the ledger. First post-fix pass: draft mean 0.65→0.46,
high-confidence calls 26%→12.5%. **Personas are pinned at boot → prompt/model changes need an
engine restart.**

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

## Mode since 2026-07-08: world-monitoring + daily digest (forecasting RETIRED)

The forecast/swarm/resolver pipeline is retired — verdict from local ledger forensics + verified
deep research: the architecture (self-generated questions, no retrieval, LLM-judge resolution)
cannot reach decision-grade skill, and prompt-level calibration is documented to fail. Full report:
`../PYTHIA-VIABILITY-REPORT-2026-07-07.md`; dated decision in `STATE.md`.

- **Auto-loop stays OFF** — `start-pythia.ps1` no longer POSTs `/loop` at boot. Don't re-enable
  without reading the viability report first.
- **Resolver retired** via `RESOLVE_INTERVAL_SEC=315360000` set in `start-pythia.ps1` (NOT `.env` —
  `.env` is tool-inaccessible on this box; the launcher env reaches the engine child process).
- **The deliverable is the digest**: "PYTHIA Daily Digest" scheduled task (7:00 AM, normal
  privileges) runs `daily-digest.py` (repo root since 2026-07-09) — one LLM call/day over
  `GET /agent/view` → `../digests/YYYY-MM-DD.md` + `latest.md` (next to the checkout, outside
  the repo). Cost ≈ $0.30/mo.
- The engine + osiris-live UI keep running; the sense loop refreshes events + brief with zero LLM
  calls. The ledger stays on disk as the closed experiment's record (`analyze-calibration.py` is
  the instrument if forecasting is ever rebuilt — then use curated questions + retrieval +
  objective resolution, not the old pipeline).

Details in `STATE.md`.
