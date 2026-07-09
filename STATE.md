# PYTHIA — STATE (record of record)

_Last updated: 2026-07-08_

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
- **Live stack: RUNNING** (background processes in a Claude Code session — they stop on session end / reboot):
  - Feeds + full UI: `osiris-live/` (nested checkout in this repo, moved 2026-07-02 from
    `~/Documents/PROJECTS/osiris-live`; gitignored), `PORT=3001 npm run dev` → <http://localhost:3001>
    (**:3000 is occupied by the separate `~/mission-control` app** — its /api routes 401, which
    silently starves the engine; always run osiris-live on :3001 now)
  - Engine: `OSIRIS_URL=http://localhost:3001 uv run python -m engine.run` → <http://localhost:8088>

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
- 2026-07-04 — **Cost retune (persona model swap):** pulled live pricing for all 340 OpenRouter
  models and swapped the 3 overpriced personas for same-tier-down alternatives: Strategist
  `anthropic/claude-sonnet-5` → `x-ai/grok-4.3` ($2/$10 → $1.25/$2.50 per M), Economist
  `openai/gpt-5.4-mini` → `openai/gpt-5-mini` ($0.75/$4.50 → $0.25/$2.00), Naturalist
  `google/gemini-3.5-flash` → `google/gemini-3.1-flash-lite` ($1.50/$9.00 → $0.25/$1.50). Skeptic +
  oracle draft (`deepseek/deepseek-v4-pro`) left unchanged — already the cheap anchor, and DeepSeek's
  own V4 Pro-vs-Flash comparison shows Flash trailing Pro by up to 45% on hard reasoning benchmarks,
  so didn't push it to Flash-tier without evidence that gap disappears on this task. Rationale is a
  pricing/tier-lineage bet (same-vendor one-rung-down models), **not** benchmark-verified for this
  specific forecasting task — the per-persona Brier track record at `GET /history` is the real
  check; watch it over the next several days before trusting the swap. `.env` updated directly
  (`SWARM_STRATEGIST_MODEL` / `SWARM_ECONOMIST_MODEL` / `SWARM_NATURALIST_MODEL`); engine restart
  required to pick it up (personas are pinned at boot).

- 2026-07-05 — **First 4-day track-record review + calibration fixes.** 885 forecasts / 96 passes;
  90 resolved true/false, 103 unresolvable, ~681 pending (only 24h has expired — week/month/year
  still pending). **Key finding: the system is badly over-forecasting.** Consensus Brier 0.249 looks
  fine only next to the wildly overconfident raw draft (0.579); the honest benchmark — always predict
  the observed base rate (6.8% true) — scores **0.064**, ~4× better. Calibration curve: forecasts
  rated 0.3–0.8 came true 0–17% of the time. Worst misses are US-weather "damage/outage" calls at
  0.70–0.78; the 6 genuine hits cluster on already-in-progress events (a tracked cyclone, daily Daraa
  shelling). Per-persona Brier (Strategist 0.18 best → Naturalist 0.45, worse than a coin flip) is
  **pre-retune old-model data** — the 07-04 swap sits at the very end of the resolved window, so the
  retune is not yet measurable. Shipped (engine restart required to take effect):
  1. **oracle.py** — draft SYSTEM prompt now carries CALIBRATION (low base rates; a P% forecast must
     mean ~P%; reserve >60% for in-progress/confirmed-trigger events) + VERIFIABILITY (predict
     observable events a later snapshot can confirm, not private meeting outcomes) discipline.
  2. **swarm.py** — same base-rate calibration reminder added to every persona's system prompt.
  3. **ledger.py** `track_record()` — adds `brier_baserate` + `base_rate` (the honest benchmark) and
     renames per-persona `model` → `current_model` (+ comment: Brier pools votes that may predate a
     model change, so the label isn't what generated all the votes).
  4. **ledger.py** `append_predictions()` — persist-time dedup: a near-duplicate (word-Jaccard ≥0.6)
     of a still-active same-horizon forecast is skipped (stays on the live deck, not re-logged), so
     one running story (Doha talks were 104 rows) no longer dominates the ledger/track record.
  5. **dashboard.html** — track strip shows a `base-rate ✓/⚠ <brier>` benchmark chip next to Brier.
  6. **test_ledger.py** — new `test_dedupe` check (5/5 pass; swarm 3/3).
  **Deferred (needs post-retune data):** inverse-Brier persona weighting / Naturalist demotion — the
  consensus is still a flat mean (swarm.py:115); revisit once ≥50 post-07-04 resolutions exist. Also
  deferred: fitting a numeric calibration map per horizon (only 24h has resolutions today). One 1970
  `expires_ms` corruption seen (1/885, a one-off oracle hallucination) — not fixed, not systemic.

- 2026-07-06 — **24h post-fix calibration checkpoint (winbox).** Re-pulled `/history` + the hourly CSV
  and re-derived Brier straight from the ledger, **segmented by forecast creation time** (the fix
  landed ~07-05 19:00 CDT). Headline Brier still **0.249 — but that's expected, not failure: 0 of the
  131 resolved forecasts were created post-fix.** A 24h forecast made just after the fix only expires
  ~07-06 19:00, so every resolution to date is a pre-fix forecast; the cumulative `/history` Brier is
  structurally **dilution-blind** to a recent prompt change for days (this is the key methodological
  lesson — segment by creation time, don't trust the headline). **Generation-side signal (the part we
  CAN see): the nudge held** — post-fix forecasts (n=64) mean prob 0.41→0.38, high-confidence (≥0.6)
  calls 18%→11%. **Pre-fix baseline quantified:** hi-conf calls predicted 68% → happened 17%; mid
  (0.3–0.6) predicted 43% → happened 8%; optimal shrink-to-base-rate **λ=0.08** — i.e. the pre-fix
  probabilities were ~92% noise vs the 11% base rate (best achievable = the 0.095 base-rate Brier).
  **Unresolvable still 50%** (155/307) — unchanged, now the dominant structural problem (judge sees
  only the snapshot, no lookup). Per-persona (all pre-fix): Strategist 0.18 / Skeptic 0.22 / Economist
  0.33 / **Naturalist 0.44** (worst — the 07-04 flash-lite retune; revert candidate if it stays worst
  post-fix). **Decision: change nothing on the calibration path** — the post-fix resolved cohort lands
  07-06 19:00 → 07-07 evening; any tweak now contaminates the before/after. Built
  `pythia-win11/analyze-calibration.py` (stdlib, self-interpreting — reproduces this segmented analysis
  from the ledger; numbers cross-checked against the manual pass) and scheduled a one-shot re-check for
  07-07 ~18:00. If post-fix Brier doesn't fall toward 0.095, next lever is the deferred numeric shrink
  map (λ≈0.1) and/or down-weighting Naturalist.

- 2026-07-07 — **Post-fix calibration verdict: the prompt nudge did NOT work.** Post-fix cohort finally
  resolved (n=16 — below the 20-sample bar, so the resolved Brier is directional, not conclusive).
  **Post-fix Brier 0.255 ≈ pre-fix 0.248 — no improvement**, and ~4× the post-fix base-rate benchmark
  (0.059; only 1/16 came true). Calibration curve: everything the model rated **≥40% came true 0%** of
  the time; all 8 calls ≥50% resolved false. **The robust signal is generation-side (n=111 post-fix
  forecasts _made_, not just the 16 resolved): mean prob 0.397, hi-conf ≥0.6 = 14%** — the model is
  still emitting ~40% forecasts against a ~6–11% realized base rate, i.e. the central over-forecasting
  the prompt was meant to correct is intact (the initial 0.41→0.38 drop even partly reverted to 0.40).
  So: the `oracle.py`/`swarm.py` **calibration prompt didn't bite**. (The other 07-05 fixes stand —
  dedup is mechanical, the base-rate chip is display-only.) **Unresolvable still 50%** (185/373).
  Naturalist still worst persona (0.43). **Recommended next lever = the deferred MECHANICAL fix: a
  numeric post-hoc shrink-to-base-rate map** — shrinking the pre-fix set at λ=0.08 took Brier
  0.248→0.094 (proof the mechanical lever works where the prompt didn't). **Awaiting go-ahead before
  implementing** (it changes what stored probabilities mean, needs an engine restart, joins the unpushed
  winbox delta). Verdict produced by the scheduled `analyze-calibration.py` re-run.
- 2026-07-08 — **STRATEGIC PIVOT: forecasting retired, repurposed to world-monitoring + daily digest.**
  Kyle's decision (Option A) after a viability deep-dive — local ledger forensics + a 106-agent
  deep-research pass (24/25 claims verified against primary sources). Full report:
  `../PYTHIA-VIABILITY-REPORT-2026-07-07.md`. Key evidence: (a) every resolved-TRUE forecast was a
  continuation of an already-in-progress event — zero genuine anticipation; (b) the LLM judge
  contradicted itself on near-identical statements (Doha meeting: false at 0.83, true at 0.68), so
  the Brier ledger itself is partly noise; (c) the literature says PYTHIA's architecture
  (self-generated questions + no retrieval + LLM-judge resolution) is validated by NO published
  benchmark, and the two missing ingredients (curated resolvable questions, retrieval at question
  time) are the field's documented bottlenecks; (d) even the best published systems trail the human
  crowd (Halawi 0.179 vs 0.149) and superforecasters beat every LLM (ForecastBench, p<0.001).
  The shrink-map lever is MOOT — it would only reproduce the base rate expensively. **What changed:**
  auto-loop OFF now (`POST /loop`) and no longer enabled at boot (`start-pythia.ps1` edit); resolver
  retired via `RESOLVE_INTERVAL_SEC=315360000` env in `start-pythia.ps1` (takes effect at next engine
  restart; interim backlog burn is cents — .env itself is tool-inaccessible on this box, hence the
  launcher-level env); NEW `../daily-digest.py` (stdlib, one LLM call/day: `GET /agent/view` →
  digest → `../digests/YYYY-MM-DD.md` + `latest.md`), driven by the **"PYTHIA Daily Digest"**
  scheduled task (daily 7:00 AM, current user, normal privileges — no elevation). Verified: loop_enabled
  false; first digest written from 250 live events. The engine keeps running (dashboard, `/agent/view`,
  globe UI) — its sense loop refreshes events + brief with ZERO LLM calls. Cost: ~$86/mo pre-retune
  pace → ~$0.30/mo. The ledger (1,009 forecasts / 384 resolutions) stays on disk as the experiment's
  record; `analyze-calibration.py` remains the instrument if forecasting is ever rebuilt on the honest
  recipe (Metaculus API questions + retrieval + objective resolution — see report Option B).
- 2026-07-09 — **First scheduled digest verified + script moved into the repo.** The "PYTHIA Daily
  Digest" task fired on schedule (7:00:01 AM, exit 0) and wrote `../digests/2026-07-09.md` from 250
  live events — the new mode's first unattended run. Two fixes shipped: (a) the LLM's own H1 stacked
  under the script's title — a leading H1 in the completion is now stripped; (b) `daily-digest.py`
  was untracked (lived above the repo root) — moved to the repo root (`.env` read from repo root,
  digests still write to `../digests/` next to the checkout so output never dirties git status).
  Scheduled task repointed at the repo and re-verified live (manual fire, exit 0, same output
  folder). Committed `a427b9d` → fork `winbox-2026-07-08` + merged into `review-fixes` (`84474fd`).
  Loop retirement re-confirmed: `GET /state` → `loop_enabled: false`; no new predictions since 07-07.
  (Note: the engine has no `GET /status` — the state check is `GET /state`; `/loop` is POST-only.)

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

## Cost (OpenRouter)

Per forecast pass = 1 oracle draft + 4 persona calls.

**Measured 2026-07-01** (250-signal brief, pre-retune models):

| Call | Model | Cost |
| --- | --- | ---: |
| Oracle draft | deepseek-v4-pro | $0.008 |
| Strategist | claude-sonnet-5 | $0.014 |
| Economist | **gpt-5.4-mini** (was gpt-5.5 @ $0.049) | ~$0.007 |
| Naturalist | gemini-3.5-flash | $0.029 |
| Skeptic | deepseek-v4-pro | $0.004 |
| **Pass total** | | **~$0.06** (was $0.104) |

**Retuned 2026-07-04** — per-M OpenRouter list prices (prompt/completion), not yet re-measured live:

| Call | Model | Prompt $/M | Completion $/M |
| --- | --- | ---: | ---: |
| Oracle draft | deepseek-v4-pro (unchanged) | $0.43 | $0.87 |
| Strategist | `x-ai/grok-4.3` (was claude-sonnet-5) | $1.25 | $2.50 |
| Economist | `openai/gpt-5-mini` (was gpt-5.4-mini) | $0.25 | $2.00 |
| Naturalist | `google/gemini-3.1-flash-lite` (was gemini-3.5-flash) | $0.25 | $1.50 |
| Skeptic | deepseek-v4-pro (unchanged) | $0.43 | $0.87 |

Completion-token-weighted estimate: ~70% cut to the swarm-deliberation portion of the pass (the
reasoning-token gotcha above means completion price dominates real cost far more than prompt
price). **Re-measure after a few live passes and compare against the 2026-07-01 baseline above** —
this table is priced-in, not measured.

- **Idle** (auto-loop OFF, current default): ~**$0/hr** — feed refresh makes no LLM calls.
- **Auto-loop ON** at 30-min interval: ~3–4 → ~2 passes/hr.
- Cheapen more: longer `LOOP_INTERVAL_SEC`, `PREDICTIONS_PER_HORIZON=2`.

## Next

**Mode since 2026-07-08: world-monitoring + daily digest.** The forecasting pipeline is retired (see
the 07-08 decision + `../PYTHIA-VIABILITY-REPORT-2026-07-07.md`); calibration work items are closed.

1. **Check the digest lands**: `../digests/YYYY-MM-DD.md` appears daily after 7:00 AM ("PYTHIA Daily
   Digest" scheduled task → `daily-digest.py` at the repo root since 07-09). If the box was asleep
   at 7, run it manually: `cd 'C:\AI World\pythia-win11\Pythia'; uv run python daily-digest.py`.
   First scheduled run verified 2026-07-09.
2. **At next engine restart** (any reboot, or the elevated one-liner in pythia.md), verify the
   retirement held: `GET /state` → `loop_enabled: false`, and the resolver stays quiet
   (`RESOLVE_INTERVAL_SEC=315360000` is set in `start-pythia.ps1`, not `.env` — the `.env` file is
   tool-inaccessible on this box). Optional cleanup while elevated: re-register "PYTHIA Oracle Ready"
   WITHOUT highest-privileges so future cycles need no UAC.
3. ~~Push the winbox delta~~ DONE 07-08/07-09: fork `winbox-2026-07-08` + `review-fixes` both carry
   the pivot (`83e1de5`, merge `f8a705a`) and the digest move/H1 fix (`a427b9d`, merge `84474fd`).
4. **If forecasting is ever revisited**, do NOT iterate on the old architecture — rebuild on the
   honest recipe (report Option B): Metaculus API questions, retrieval at question time (self-hosted
   SearXNG/crawl4ai), objective platform resolution, shrinkage. Ceiling: crowd-adjacent, not expert.
5. Optional: surface `digests/latest.md` in the osiris-live deck or serve it from the engine.
6. Optional: `run-all.sh` still pings Ollama `:11434` (spurious warning under OpenRouter).

Design detail: `~/.claude/plans/typed-herding-melody.md`. Durable notes: `~/.claude/memory/domain/pythia.md`.
