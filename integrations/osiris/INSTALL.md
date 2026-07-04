# Osiris integration overlay

PYTHIA is the engine in this repo **plus** a thin overlay for the
[Osiris](https://github.com/simplifaisoul/osiris) dashboard, which provides the live
globe + world feeds. These are the source files for the overlay (kept in sync with a
working install). Osiris itself is upstream — clone it separately, then apply this.

## New files to copy into your Osiris checkout

| File here | Goes to |
|---|---|
| `PythiaPanel.tsx` | `src/components/PythiaPanel.tsx` — the oracle / predictions deck |
| `DeliberationModal.tsx` | `src/components/DeliberationModal.tsx` — swarm deliberation popup (gauge + per-agent votes) |
| `PythiaStatus.tsx` | `src/components/PythiaStatus.tsx` — top-right status + model picker |
| `CreditsModal.tsx` | `src/components/CreditsModal.tsx` — credits |
| `FloatingWindow.tsx` | `src/components/FloatingWindow.tsx` — movable/resizable window shell |
| `ChatBox.tsx` | `src/components/ChatBox.tsx` — chat with the oracle |
| `SplashScreen.tsx` | `src/components/SplashScreen.tsx` — fish-around-the-eye load screen |
| `HeadlineTicker.tsx` | `src/components/HeadlineTicker.tsx` — bottom world-headline ticker |
| `routes/engine-proxy-route.ts` | `src/app/api/engine/[...path]/route.ts` — same-origin proxy to the engine |
| `routes/polymarket-route.ts` | `src/app/api/polymarket/route.ts` — Polymarket crowd odds |
| `routes/nws-alerts-route.ts` | `src/app/api/nws-alerts/route.ts` — NWS storm/flood polygon zones |
| `routes/frontlines-route.ts` | `src/app/api/frontlines/route.ts` — Ukraine territory control (DeepStateMap, no key) |
| `routes/displacement-route.ts` | `src/app/api/displacement/route.ts` — forced displacement / refugees (UNHCR, no key) |
| `routes/economy-route.ts` | `src/app/api/economy/route.ts` — cost-of-living inflation (World Bank, no key) |
| `routes/censorship-route.ts` | `src/app/api/censorship/route.ts` — internet censorship anomalies (OONI, no key) |
| `routes/health-outbreaks-route.ts` | `src/app/api/health-outbreaks/route.ts` — disease outbreaks (WHO, no key) |
| `routes/unrest-route.ts` | `src/app/api/unrest/route.ts` — civil unrest / protests (GDELT events, no key, no deps) |
| `routes/food-security-route.ts` | `src/app/api/food-security/route.ts` — food insecurity (WFP HungerMap, no key) |
| `routes/unemployment-route.ts` | `src/app/api/unemployment/route.ts` — unemployment (World Bank, no key) |
| `routes/gdp-growth-route.ts` | `src/app/api/gdp-growth/route.ts` — GDP growth (World Bank, no key) |
| `routes/poverty-route.ts` | `src/app/api/poverty/route.ts` — extreme poverty (World Bank, no key) |
| `lib/countryCentroids.ts` | `src/lib/countryCentroids.ts` — shared ISO3/ISO2/name → centroid for country layers |
| `lib/useEngineState.ts` | `src/lib/useEngineState.ts` — shared engine-state hook (SSE via `/api/engine/state/stream`, 2.5s poll fallback); exports the `Prediction`/`Snap` types |

## Edits to existing Osiris files (high level)

- `src/app/page.tsx` — render `<PythiaStatus/>`, the floating windows, `<CreditsModal/>`;
  a right-toolbar with Layers/Chat/Markets/Alerts/PYTHIA(Eye)/Search buttons; globe-spin
  control + a **light/dark theme toggle** (Sun) by the 2D/Sat toggles, persisted to
  localStorage as `pythia-theme` (restored in a mount effect — hydration-safe); route news
  `onWatchFeed` to floating windows; default the left Layers bar off. Calls
  **`useEngineState()`** once at top level and passes `snap`/`connected` into `PythiaPanel`
  (which no longer polls); `DeliberationModal` is rendered HERE (inside `.pythia-scope`) so
  map popups can open it via the `window.openPythiaDeliberation(id)` global (registered next
  to `openOsirisIntel`, reading a `predictionsRef`); deck-card hover sets `focusPredId`;
  `predictions` + `focusPredictionId` are passed to `OsirisMap`; `activeLayers` gains
  `predictions: true`; the map `key` is `light|dark` (remount only when the basemap actually
  changes); the theme toggle adds `body.theme-switching` for 700ms. Theme classes are swapped
  via `classList` (never `body.className =`, which wiped `theme-switching`/`antialiased`); the
  right tool strip shifts to `right-[356px]` while the deck is open; the two duplicate mobile
  SUPPORT-PROJECT blocks were removed (2026-07-02 audit).
- `src/app/globals.css` — **Doto** dot-matrix display font (`--font-doto`, `.pythia-display`);
  a `body.theme-light` block (soft-Apple whites/greys, frosted glass) + `.pythia-ticker-bg` +
  `.pythia-scope` readable-color overrides. The global `* { transition: 0.6s }` is scoped to
  `body.theme-switching *` so data ticks stop animating every element. Light-theme text tokens
  are **WCAG-AA computed** (cyan `#0a6f8a`, green `#10733d`, purple `#5f3ecc`, muted `#5b6472`,
  orange `#a85800`); stock hardcoded hexes are overridden by class substring
  (`body.theme-light [class*="D4AF37"]` → `#7d631c`, `[class*="14F195"]` → `#096f4b`); the black
  bottom bars keep the dark text palette by re-declaring the vars on `.pythia-ticker-bg` and
  `[class*="z-[198]"]`; `--fw-shadow`/`--fw-header-bg` theme the FloatingWindow chrome.
- `src/app/layout.tsx` — load the Doto + JetBrains Mono Google Fonts.
- `src/components/OsirisMap.tsx` — `nws-alerts` + `frontlines` polygon sources with
  `nws-fill`/`nws-outline` and `frontline-fill`/`frontline-line` layers; the 9 SOCIAL
  circle layers (`soc-*`) **sized by per-layer log-normalized severity** (`_norm` from each
  route's metric: displacement `total`, unrest `events`, food `people`, inflation
  `inflation`, censorship `anomalies`, unemployment `unemployment`, gdp `mag`, poverty
  `poverty`) with worst-hit **labels** (filter `_norm ≥ 0.7`) and click **popups** showing
  the route's `label`; a **`pythia-predictions`** source + `pythia-pred-glow`/`-core`/`-focus`
  circle layers added last (topmost) — color by horizon (24h red / week gold / month cyan /
  year violet), radius by consensus probability, white stroke ring on swarm SPLIT, focus
  ring filtered on the hovered card's id; marker click → popup with statement/consensus +
  `[ VIEW DELIBERATION ]` button; new `predictions` + `focusPredictionId` props;
  **light theme → CARTO Positron basemap** (dark-matter otherwise, via the page-level
  `key={light|dark}` remount).
- `src/components/LayerPanel.tsx` — an **ORACLE group** (`predictions` toggle, Eye icon,
  first in the rail); "Storm / Flood Zones", "Conflict / War Zones" and "War Front /
  Territory" toggles; the SOCIAL group of 9 keyless layers (Displacement, Disease Outbreaks,
  Inflation, Censorship, Civil Unrest, Food Insecurity, Unemployment, GDP Growth, Extreme
  Poverty); plus Recon Balloons, Radiation Monitors, News Intel toggles; removed the SDK
  group and the theme toggle.
- `src/components/HeadlineTicker.tsx` rendered in `page.tsx` at `bottom-[22px]` (stacked above
  the stock 22px LIVE status bar, not covering it); mobile bottom-nav gains an ALERTS tab.
  `LayerPanel.tsx`'s mobile drawer uses theme vars instead of `text-white/…` (readable in light
  mode). `PythiaPanel` is capped at `max-h-[min(82vh,calc(100dvh_-_440px))]` so the deck always
  ends above the fixed deck/chat/credits/theme button cluster (`bottom-[150px]`, 208px tall).
  `FloatingWindow` clamps dragging to the viewport.
- `src/components/MarketsPanel.tsx` — header changed from `<button>` to `<div role="button">`
  (it contained the Maximize `<button>` — nested buttons are invalid HTML and threw a React
  hydration error).
- `src/app/layout.tsx` + `public/manifest.json` — PYTHIA name/icons (home-screen).

All UI talks to the engine only through `/api/engine/*`, which forwards to
`PYTHIA_ENGINE_URL` (default `http://localhost:8088`).
