# PYTHIA — STATE (record of record)

_Last updated: 2026-07-02_

## Status

- Forked from `jangles-byte/Pythia`. Local: `~/Documents/PROJECTS/Pythia` (`origin` = upstream — fork before pushing).
- **Multi-model swarm: DONE + verified.** Each persona votes with a different OpenRouter model.
- **Calibration/backtesting: SHIPPED + verified (2026-07-02).** Every pass persists to
  `runs/predictions.jsonl`; an LLM judge resolves forecasts on horizon expiry
  (`runs/resolutions.jsonl`) → Brier track record (overall / vs-draft / per-horizon /
  **per-persona**) at `GET /history`, in the SSE snapshot (`kind="track"`), and as a dashboard
  strip. Restart-safe: memory is only a cache of the jsonl files.
- **Light-mode audit fixes: SHIPPED + verified (2026-07-02, /site-audit + Codex cross-check).**
  Deck no longer overlaps the deck/chat/credits/theme button cluster (PythiaPanel max-h now
  `min(82vh, 100dvh−440px)`); light-theme text tokens darkened to WCAG AA (computed ratios);
  stock hardcoded hexes (`#D4AF37`, `#14F195`) overridden via `body.theme-light [class*=…]`;
  black bottom bars keep dark-palette vars pinned; PYTHIA ticker lifted above the LIVE bar
  (`bottom-[22px]`); right tool strip shifts left of the open deck; 2 duplicate mobile
  SUPPORT-PROJECT blocks deleted; theme swap now uses `classList` (preserves `theme-switching`
  - `antialiased` — the 700ms fade actually runs now); FloatingWindow chrome themed via
  `--fw-shadow`/`--fw-header-bg` + drag clamped to viewport. Codex transcript in session
  scratchpad; user-visible "giant stacked pills" was a stale browser-cached CSS chunk (hard
  refresh) on top of the real overlap bug. Follow-up same day: stock `MarketsPanel.tsx` header
  was a `<button>` containing the Maximize `<button>` (invalid HTML → React hydration error);
  header is now `<div role="button" tabIndex={0}>` with Enter/Space + `aria-expanded`. Verified:
  fresh load + panel open = 0 console errors; maximize/restore/collapse all work. Now the 7th
  tracked-file edit in `integrations/osiris/tracked-edits.patch`.
- **Predictions ON the globe: SHIPPED + verified (2026-07-02).** `pythia-predictions` markers in
  OsirisMap (color=horizon, size=probability, white ring=SPLIT), click → popup →
  `[ VIEW DELIBERATION ]` opens the modal; deck-card hover draws a focus ring on the marker. The 9
  social circles are now **sized by real severity** (per-layer log-normalized metric) with labels +
  popups. Deck consumes **SSE** (poll only as fallback); theme persists to localStorage.
- **Live stack: runs 24/7 on the Windows 11 desktop (since 2026-07-03).** Exported via
  `~/Desktop/pythia-win11/` (repo + prefilled `.env` + `setup.ps1`/`start-pythia.ps1`/
  `install-autostart.ps1` + `WINDOWS-SETUP.md`); the desktop's `runs/` ledger continues the
  Mac's track record. **Mac stack: STOPPED 2026-07-03** — this checkout is now for development.
  To run locally again:
  - Feeds + full UI: `osiris-live/` (nested checkout in this repo, moved 2026-07-02 from
    `~/Documents/PROJECTS/osiris-live`; gitignored), `PORT=3001 npm run dev` → <http://localhost:3001>
    (**:3000 is occupied by the separate `~/mission-control` app** — its /api routes 401, which
    silently starves the engine; always run osiris-live on :3001 now)
  - Engine: `OSIRIS_URL=http://localhost:3001 uv run python -m engine.run` → <http://localhost:8088>,
    then `POST /loop {"enabled":true}` (defaults off at boot)

## Decisions (dated)

- 2026-07-01 — Backend: **OpenRouter** over Ollama. Ollama isn't installed and `~/MiroFish/.env`
  is absent, so stock PYTHIA couldn't run; OpenRouter key already exists in `~/.hermes/.env`. Bonus:
  fixes the correlated-swarm problem.
- 2026-07-01 — **Skip** Codex/Claude-subscription CLI backends — subscription-auth'd interactive
  agents are the wrong transport for an always-on server.
- 2026-07-01 — Persona→model (one lab each): Strategist=`anthropic/claude-sonnet-5`,
  Economist=`openai/gpt-5.4-mini`, Naturalist=`google/gemini-3.5-flash`,
  Skeptic + oracle draft=`deepseek/deepseek-v4-pro`.
- 2026-07-01 — Raised token budgets + null-guarded `_complete` for reasoning models (see gotcha).
- 2026-07-01 — Live run on real feeds via a stock Osiris checkout (`osiris-live`) + copied keyless
  overlay routes; did NOT apply the brittle themed-UI edits. Added a keyless dashboard at `GET /`.
- 2026-07-01 — **Cost tuning:** Economist `gpt-5.5` → `openai/gpt-5.4-mini` (~7× cheaper output;
  note `gpt-5.5-mini` does not exist on OpenRouter); `LOOP_INTERVAL_SEC` 900 → 1800 (30 min). Engine
  restarted to apply. See Cost below.
- 2026-07-01 — **Full UI rollout (core):** copied the 8 overlay components + engine-proxy route into
  `osiris-live`; additively mounted PythiaStatus/PythiaPanel(+DeliberationModal)/HeadlineTicker +
  an Eye toggle in `src/app/page.tsx` (after the map `ErrorBoundary`), reusing Osiris's existing
  `flyToLocation` state for `onLocate`. Added `pythia-display`/`--font-doto`/`animate-ticker` to
  `globals.css`. Verified: page compiles (0 errors), components SSR into HTML, `/api/engine/*` proxy
  live, clicking a prediction flies the globe.
- 2026-07-01 — **UI polish:** real **Doto** dot-matrix font (Google Fonts `<link>` in `layout.tsx`);
  oracle **Chat** (FloatingWindow + ChatBox, `/api/engine/chat`) + **Credits** modal, via a right-side
  control cluster (deck/chat/credits). **Readability fix:** the active Osiris theme uses low-contrast
  purples (`--text-muted: #4A148C` near-invisible; `--gold-primary`/`--cyan-primary` purple) — scoped
  brighter values in a `.pythia-scope` class (wraps the mounts; added to the two portaled modals'
  roots). Verified: compiles clean, chat proxy round-trips (200).
- 2026-07-01 — **Social layers + light/dark theme (the OsirisMap surgery):** added 9 social
  circle layers (displacement/disease/unrest/food/inflation/censorship/unemployment/gdp/poverty)
  by mirroring the earthquake point-feed lifecycle — `SOCIAL_LAYERS` const + source/layer loop at
  map-init + a data-sync `useEffect` in `OsirisMap.tsx`; page.tsx fetches the feeds into `data`
  (gated on `activeLayers`); a SOCIAL group in `LayerPanel.tsx`. **Light theme:** `body.theme-light`
  var block + `.pythia-scope` light overrides in `globals.css`, a Sun/Moon toggle in the control
  cluster (`osirisTheme` extended to `'light'`), CARTO **Positron** basemap when light (OsirisMap
  remounts via `key={osirisTheme}`). **Verified with Playwright (headless):** globe renders in dark
  AND light (screenshots), 0 console errors from our code, all 9 social feeds fetch 200 on toggle
  with coords. (Only console errors are Osiris's pre-existing CoinGecko CORS.) **Full overlay now
  rolled out.**

- 2026-07-02 — **Calibration slice shipped** (STATE's declared "real gap"): new `engine/ledger.py`
  (append-only jsonl under `runs/`, horizon-expiry math `HORIZON_MS`, history join, Brier
  `track_record()`) + `engine/resolver.py` (batched LLM judge; one call per sweep, none when
  nothing due; rides `SenseLoop` every `RESOLVE_INTERVAL_SEC=1800`; `POST /resolve` for manual).
  Judge = `JUDGE_MODEL` env, defaults to the deepseek draft model, own client so `/model` switches
  never touch it. **`unresolvable` verdicts are terminal** (never re-judged). Judge verified live:
  refused to guess on a fabricated window AND on an unconfirmed cyclone landfall, with
  evidence-citing rationales. Cost <$0.01/sweep.
- 2026-07-02 — **Engine hardening:** `/predict` TOCTOU fixed (claim `generating` synchronously);
  boot no longer double-fetches all 23 feeds; one retry w/ 2s backoff on 5xx/transport in
  `_complete`; personas now see the same `BRIEF_CHARS=6500` snapshot as the drafter (was 2600);
  Polymarket anchor note only when `[MARKET-ODDS]` present; **`POST /model` = draft oracle only**
  (personas get dedicated clients, pinned at boot; response now returns `swarm_models`);
  `agent/events?since=` actually works (feed-derived timestamps + first-seen registry keyed by
  dedup key); dropped unused `Prediction.drivers`; version aligned at **0.3.0** everywhere.
- 2026-07-02 — **UI: SSE + globe markers + data-driven circles + polish** (all mirrored to
  `integrations/osiris/`): new `src/lib/useEngineState.ts` (EventSource on
  `/api/engine/state/stream`, 2.5s poll fallback + 15s SSE retry) called once in `page.tsx`;
  PythiaPanel is now prop-driven (no polling); DeliberationModal lifted to page level so map
  popups open it via `window.openPythiaDeliberation(id)`; `pythia-predictions`
  glow/core/focus layers (topmost) + ORACLE LayerPanel group (`predictions: true` default);
  social circles sized by per-layer log-normalized `_norm` + labels (`_norm≥0.7`) + popups;
  theme persisted to `localStorage 'pythia-theme'`; map remounts only when the basemap actually
  changes (`key = light|dark`); global `*{transition:0.6s}` scoped to `body.theme-switching`;
  type floor raised 7–9px → 10px; aria-labels on icon buttons; offline status dots are hollow
  rings. Verified with Playwright: SSE stream is the only state transport (0 poll requests),
  markers render both themes, card→modal→fly→marker→popup→modal loop works, theme survives reload.
- 2026-07-02 — **Overlay durability:** the 6 tracked-file Osiris edits now exist as a real patch —
  `integrations/osiris/tracked-edits.patch` (apply with `git apply` on a stock clone). Born of a
  near-disaster: a `git stash` round-trip in `osiris-live` dropped the (uncommitted!) overlay edits;
  recovered via `git fsck --unreachable` → `git stash apply <sha>`. **Never `git stash` in
  osiris-live** — the overlay lives only in the worktree. (Also: after any worktree revert/restore
  while `next dev` runs, nuke `.next` — Turbopack served a stale CSS chunk with no theme-light rules.)

## Changes (files)

- `engine/config.py` — Hermes-`.env` key auto-read; per-persona `SWARM_*` backend fields + `__post_init__`.
- `engine/oracle.py` — `Oracle(base,key,model,extra_headers)` doubles as a per-persona client;
  `_headers()`; null-content guard; larger token budgets.
- `engine/runtime.py` — `PERSONA_CLIENTS` (reuses the primary oracle when the backend is identical).
- `engine/swarm.py` — per-client `_ask` + single-retry fallback; `deliberate(persona_clients, …)`.
- `engine/pipeline.py` — passes `PERSONA_CLIENTS` + fallback.
- `engine/dashboard.html` + `server.py` `GET /` — self-contained live SSE dashboard (+ track strip).
- `engine/ledger.py` / `engine/resolver.py` — calibration: jsonl persistence + LLM judge (2026-07-02).
- `engine/test_swarm_backends.py` — pure self-check (3 checks); `engine/test_ledger.py` (4 checks).
- `.env` / `.env.example` — OpenRouter multi-model defaults (+ `JUDGE_MODEL`, `RESOLVE_INTERVAL_SEC`).
- `README.md` / `CLAUDE.md` / `STATE.md` — fork docs.
- `integrations/osiris/` — overlay source of record: components + routes + `lib/useEngineState.ts`
  - **`tracked-edits.patch`** (the 6 core-file edits as a git patch).

## Verification

- Self-checks: 3/3 `uv run python -m engine.test_swarm_backends`; 4/4 `uv run python -m engine.test_ledger`
  (expiry math, jsonl round-trip through a reload, due/resolved exclusion, hand-computed Brier incl.
  per-persona, judge-output parsing).
- Live run (2026-07-01, real feeds): **250 signals / 18 domains → 9 predictions, 7 SPLITs.**
  Genuine cross-model spread (cyclone: Gemini 80% vs Sonnet 30%; Zaporizhzhia: DeepSeek 60%
  base-rate vs GPT 8% snapshot-grounded). Oracle draft → swarm consensus working; ungrounded drafts
  pulled down (e.g. Bahrain 50% → 16%).
- Live calibration loop (2026-07-02): pass → 12 lines in `runs/predictions.jsonl` with sane
  `expires_ms`; hand-expired entries + restart + `POST /resolve` → judged, resolution persisted,
  `/history` status flips, track strip renders; second restart → identical state (disk is truth).
  Double `POST /predict` → "already running" (one run). `POST /model` leaves persona models alone.
- Live UI (2026-07-02, Playwright headless on :3001): one long-lived `/api/engine/state/stream`,
  **zero** `/state` polls; prediction markers render dark + light (screenshots); full loop
  deck-card → deliberation modal → fly-to → marker → map popup → modal verified; displacement
  circles visibly size-varied; theme persists across reload; 0 console errors from our code
  (only doubleclick ad noise from a YouTube embed).

## Cost (OpenRouter, measured 2026-07-01)

Per forecast pass = 1 oracle draft + 4 persona calls. Measured on a 250-signal brief:

| Call | Model | Cost |
|---|---|---:|
| Oracle draft | deepseek-v4-pro | $0.008 |
| Strategist | claude-sonnet-5 | $0.014 |
| Economist | **gpt-5.4-mini** (was gpt-5.5 @ $0.049) | ~$0.007 |
| Naturalist | gemini-3.5-flash | $0.029 |
| Skeptic | deepseek-v4-pro | $0.004 |
| **Pass total** | | **~$0.06** (was $0.104) |

- **Idle** (auto-loop OFF, current default): ~**$0/hr** — feed refresh makes no LLM calls.
- **Auto-loop ON** at 30-min interval: ~3–4 → ~2 passes/hr ⇒ **~$0.10–0.13/hr**.
- Manual PREDICT = ~$0.06 each. `/chat` questions ≈ $0.01–0.02 each.
- Cheapen more: `SWARM_ECONOMIST_MODEL=openai/gpt-5-mini`, longer `LOOP_INTERVAL_SEC`,
  `PREDICTIONS_PER_HORIZON=2`. Naturalist (gemini-flash) is now the priciest — heavy reasoning tokens.

## Next

1. **Let the track record accumulate**: turn the auto-loop on for a few days so 24h/week horizons
   expire naturally and real Brier numbers appear (first genuine resolutions ≈ 24h after a pass).
   Then judge the judge: spot-check `runs/resolutions.jsonl` rationales.
2. Fork to an owned remote + open a PR upstream if sharing.
3. Optional: surface the track record in the osiris-live UI (deck header chip reading
   `snap.track_record` — the SSE payload already carries it).
4. Optional: `run-all.sh` still pings Ollama `:11434` (spurious warning under OpenRouter).

Design detail: `~/.claude/plans/typed-herding-melody.md`. Durable notes: `~/.claude/memory/domain/pythia.md`.
