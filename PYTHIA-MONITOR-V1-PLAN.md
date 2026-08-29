# PYTHIA Monitor v1 — Research, Product Plan, and Handoff

**Status:** planning / no implementation started  
**Recorded:** 2026-08-28  
**Repository state reviewed:** `boostedchaos/Pythia`, branch `review-fixes`  
**Purpose:** self-contained handoff for resuming this work on another computer

---

## 1. Executive decision

PYTHIA should become a **private, always-on homelab intelligence service**, not a general forecasting oracle.

The proposed product is:

> Tell me what changed in the parts of the world I care about, why it matters, and show me the receipts.

The runtime should focus on:

1. collecting trustworthy observations;
2. tracking evolving stories over time;
3. detecting material changes;
4. generating a cited daily brief;
5. issuing a small number of high-signal alerts;
6. supporting grounded search/chat;
7. exposing the same evidence to other agents through HTTP and MCP.

The existing forecasting experiment should be preserved as research history, but removed from the normal runtime. If forecasting is revisited, it should live in an explicit research mode and use a different methodology.

---

## 2. Confirmed user requirements

- **Audience:** private tool for one user, not currently a public SaaS or polished multi-user product.
- **Deployment:** always-on homelab service, deployable to either an Unraid server or a VM/container host in a Proxmox cluster.
- **Current usage:** PYTHIA is not installed or running anywhere now. There is no live deployment to preserve.
- **Primary intelligence beats:** AI, cybersecurity, global politics, healthcare regulation, and markets.
- **Model provider:** OpenRouter is acceptable and probably the preferred synthesis provider.
- **Implication:** no local GPU, Ollama dependency, or workstation-specific launcher is required for Monitor v1.

Unanswered product/deployment questions are recorded in Section 16.

---

## 3. What exists today

The current fork is an extension of `jangles-byte/Pythia`, itself built around Osiris.

Current data path:

```text
23 Osiris HTTP feeds
        ↓
ad-hoc feed-specific normalization
        ↓
up to 250 in-memory WorldEvent objects
        ↓
count-ordered, 6,500-character prose WorldBrief
        ├── HTTP API and grounded chat
        ├── daily-digest.py → one OpenRouter call
        └── forecast → multi-model swarm → ledger → LLM resolution judge
```

Important existing work worth preserving:

- Osiris feed ingestion and normalization.
- FastAPI service and SSE state stream.
- `/agent/view`, `/agent/events`, `/world`, and chat concepts.
- Multi-model OpenRouter configuration patterns.
- A useful set of Pydantic domain objects.
- The daily digest experiment.
- UI overlay work and real-time map integration.
- The calibration ledger and its data as an archived experimental record.
- The documented evidence that the forecasting design failed its benchmark.
- Tests for the ledger and per-persona model wiring.

The current branch has only two local self-check modules and no meaningful GitHub CI.

---

## 4. Forecasting experiment: conclusion and preservation policy

The fork added a genuinely multi-model forecasting council, persistence, resolution, and Brier scoring. The experiment accumulated:

- 1,009 forecasts;
- 384 resolutions;
- severe over-forecasting;
- approximately 50% unresolvable outcomes;
- no genuine anticipatory hits in the reviewed sample;
- a simple observed base-rate forecast that beat the system by roughly 4×;
- inconsistent LLM-judge outcomes on similar statements.

Prompt-based calibration did not materially improve the result.

The strategic conclusion recorded on 2026-07-08 was correct:

- automatic forecasting should remain retired;
- the live sensing layer remains useful;
- a daily world digest is a more defensible product;
- applying a numeric shrink map would merely reproduce the base rate at greater cost.

### Preservation policy

- Keep `review-fixes` and the existing ledger code/history intact as the experiment archive.
- Do not delete the research record.
- Do not use the old LLM-judge labels to weight future production decisions.
- Do not import upstream’s Brier-weighted persona consensus into Monitor v1.
- If forecasting is revisited, build it as a separate research module using externally defined resolvable questions, retrieval at forecast time, objective external resolution, crowd/base-rate benchmarks, time-separated evaluation, and explicit calibration/shrinkage.

---

## 5. Critical audit findings

### 5.1 Forecasting is not actually retired in code

The runtime still performs forecast-related work:

- `engine/server.py` calls `run_prediction(trigger="boot")` on every startup.
- `SenseLoop` still invokes the resolver.
- Resolver retirement depends on an enormous `RESOLVE_INTERVAL_SEC` value set by a workstation launcher outside the normal repository configuration.
- A clean install or normal `run-all.sh` launch restores the default 30-minute resolver interval.
- Boot forecasting can spend money and append new ledger entries even while the continuous forecast loop is disabled.

Required fix: introduce a real operating mode.

```text
PYTHIA_MODE=monitor       # forecasting, swarm, ledger append, resolver unreachable
PYTHIA_MODE=research      # forecasting explicitly enabled
```

Monitor mode must exclude forecast work by construction, not convention.

### 5.2 Unsafe default network exposure

Current behavior:

- `ENGINE_HOST` defaults to `0.0.0.0`.
- FastAPI permits every CORS origin.
- There is no authentication.
- Mutating endpoints include model switching, chat, manual prediction, and loop control.
- Provider credentials can therefore be consumed indirectly by any client able to reach port 8088.

Required posture:

- bind the engine to an internal container network;
- publish only the web UI;
- default a standalone engine to `127.0.0.1`;
- require a bearer token if the API is exposed through Tailscale/LAN;
- configure explicit CORS origins;
- keep OpenRouter credentials available only to the engine container.

### 5.3 Feed failures are invisible downstream

`engine/osiris_intake.py` converts timeouts, HTTP failures, parsing failures, and schema drift into empty result lists, usually logged only at debug level.

The rest of the product cannot distinguish a healthy-empty feed from a stale feed, timeout, HTTP error, schema change, or normalization failure.

Required new model:

```text
FeedRun
  source/feed identity
  status: healthy | empty | stale | error
  started_at / completed_at
  HTTP status
  source data timestamp
  items received / accepted / rejected
  last successful fetch
  safe error summary
```

Expose `/feeds/health` and include coverage warnings in the UI and brief.

### 5.4 Event identity and continuity are not durable

Current behavior:

- every normalized event gets a random ID;
- deduplication is based on the first 80 lowercase title characters;
- first-seen timestamps exist only in memory;
- restarts erase continuity;
- similar headlines can collide;
- reworded updates become unrelated events;
- `since` semantics are not durable.

Required stable identity order:

1. upstream source ID;
2. canonical source URL;
3. normalized source-specific natural key;
4. deterministic content fingerprint as fallback.

Persist `first_seen`, `last_seen`, source timestamp, revisions, and observation/story relationships in SQLite.

### 5.5 Coordinate-zero bug

The coordinate parser uses expressions such as:

```python
lat = d.get("lat") or d.get("latitude")
```

A valid coordinate of `0` is treated as absent. Replace truthiness-based selection with explicit `is not None` logic and add regression tests for latitude/longitude zero.

### 5.6 World-brief selection is biased

`engine/world_state.py` sorts domains by raw event count, takes up to eight events per domain, concatenates them, and truncates the result to 6,500 characters.

Consequences:

- noisy domains consume the prompt first;
- rare high-value signals may be truncated;
- salience lacks dependable recency decay;
- source reliability and corroboration are ignored;
- multiple reports of one story appear as additional global activity;
- keyword matching can produce context-blind salience.

Future ranking should consider:

```text
severity
× recency
× source reliability
× novelty/change
× user relevance
× cross-source corroboration
```

Use per-beat and per-source budgets so one feed cannot starve the rest.

### 5.7 Daily digest is a snapshot, not change intelligence

`daily-digest.py` currently:

- selects the eight highest-salience events in every domain;
- sends them directly to OpenRouter;
- does not compare with the previous digest;
- does not know which stories are new, escalating, continuing, or resolved;
- does not include source URLs;
- cannot report missing/stale feeds;
- hardcodes OpenRouter instead of using the engine provider abstraction;
- lacks retries, durable scheduling, atomic output, and tests.

The future brief should be assembled from structured deltas:

```text
NEW
CHANGED
ESCALATING
DE-ESCALATING
RESOLVED/EXPIRED
WATCHLIST MATCHES
FEED COVERAGE WARNINGS
```

The LLM should rewrite selected evidence, not select evidence from an undifferentiated blob. Every published claim should cite validated observation IDs and URLs.

### 5.8 Stale API timestamps in monitor mode

`/agent/view.generated_at` uses `STATE.last_run_ms`, which changes when predictions are set, not when the cheap sensing loop refreshes the world.

Required timestamps:

- `world_refreshed_at`
- `last_successful_feed_at`
- `digest_generated_at`
- `forecast_generated_at` only in research mode

### 5.9 Lifecycle and persistence weaknesses

- sensing and boot prediction can duplicate feed fetches;
- long feed timeouts delay the entire `asyncio.gather`;
- background tasks are not explicitly cancelled on shutdown;
- event and feed state are memory-only;
- several JSON files are overwritten non-atomically;
- subscriber queues are silently discarded when full;
- no source health is visible to API clients;
- no schema fixtures protect feed adapters;
- no production CI or container build verification exists.

---

## 6. Upstream divergence analysis

At the time of this review:

- fork branch: seven commits ahead of the shared base;
- fork branch: 48 commits behind `jangles-byte/Pythia/main`;
- merge base: `ed9e2f6e02277a997bf7d4e3f28f6907c4cbfa3a`.

Upstream added approximately 48 feeds, MCP, signal rules, Morning Brief scheduling, webhooks, watchlists, feed-latency improvements, SEC/CISA/FAA/IODA/wastewater/climate/NHC/GDACS/market/camera integrations, a global health score, and a much larger forecast/UI surface.

### Decision

Do **not** wholesale merge or rebase Monitor v1 onto current upstream.

Reasons:

- upstream doubled down on the forecasting architecture this fork disproved;
- its breadth adds large operational and UI complexity;
- many upstream features are forecast-dependent;
- 48 feeds increase fragility and noise unless tied to actual user needs;
- the products have diverged philosophically.

### Harvest selectively

Good candidates to adapt after review:

- MCP transport and tool packaging;
- alerts and notification concepts;
- Morning Brief scheduling;
- bounded feed latency;
- selected source adapters;
- on-demand cameras only if visual verification proves useful;
- feed-health work;
- watchlist concepts independent of forecasts.

Do not import without redesign:

- Brier-weighted persona voting;
- self-judging forecast resolution;
- the global 1–100 health score;
- forecast-driven market watchlists;
- every feed merely to increase coverage;
- webhooks without SSRF-safe destination validation and private-network protections.

---

## 7. Target product definition

PYTHIA Monitor v1 is a **personal intelligence compiler**.

### Core questions

1. What changed since the last update?
2. What deserves attention now?
3. Why does it matter?
4. Which sources support the claim?
5. What should remain on the watchlist?

### Primary outputs

- cited morning brief;
- optional evening delta;
- immediate high-confidence alerts;
- searchable story timeline;
- dashboard for exploration;
- grounded chat over stored evidence;
- HTTP and MCP access for other agents.

### Explicit non-goals for v1

- predicting the future;
- multi-model persona theater;
- a single “state of the world” score;
- public multi-user hosting;
- ingesting every available feed;
- replacing a professional terminal or financial-data product;
- running a local LLM or requiring a GPU;
- autonomous actions based only on LLM conclusions.

---

## 8. Proposed homelab architecture

```text
                  Tailscale / reverse proxy / SSO
                               │
                         Pythia Web UI
                               │
                    private Docker network
                               │
                       Pythia Engine API
                  ┌────────────┼────────────┐
                  │            │            │
             Collectors    SQLite       OpenRouter
                           volume       synthesis
                  │
          primary sources and feeds
                  │
             Telegram / ntfy / email
```

### Container layout

Initial Compose stack:

1. **web**
   - Pythia/Osiris-derived dashboard.
   - Only published application port.
   - Proxies API requests to `engine:8088`.
   - No provider secrets.

2. **engine**
   - FastAPI collectors, persistence, ranking, digest, chat, and scheduling.
   - Internal network only.
   - OpenRouter secret.
   - Persistent `/data` volume.
   - Non-root user.
   - Health/readiness endpoints.

Optional later: a reverse proxy only if the homelab does not already provide one.

No Postgres is required initially. SQLite in WAL mode is sufficient for a single-user service.

### Deployment target

Create one portable Docker Compose stack that runs on both Unraid Docker/Compose and a Debian/Ubuntu VM on Proxmox.

Because inference is remote, compute requirements should be modest. Do not require a GPU. Avoid treating Docker-inside-unprivileged-LXC as the primary installation path for the first release; a VM is the lower-friction Proxmox target.

### Required container qualities

- pinned base images and dependencies;
- non-root processes;
- health checks;
- restart policy;
- graceful shutdown;
- persistent data volume;
- atomic migrations;
- secrets outside source control;
- GHCR images built and tested by CI;
- documented backup/restore;
- one command to deploy or upgrade.

---

## 9. Target persistent data model

### Source

- ID and display name
- source class
- canonical domain
- reliability tier
- expected refresh cadence
- configured/enabled state
- terms/license notes

### FeedRun

- source/feed ID
- start/completion timestamps
- health status
- HTTP result
- received/accepted/rejected counts
- source data timestamp
- last successful fetch
- safe error message

### Observation

- stable ID
- source ID and upstream ID
- canonical URL
- source and fetched timestamps
- title and body
- entities and geography
- beat/topic classification
- normalized severity
- raw payload or content hash
- supersedes/revision relationship

### Story

- stable ID and canonical title
- first seen / last observed / last changed
- status: new | active | escalating | de-escalating | resolved | stale
- linked observations
- entities, geography, and beats
- evidence/corroboration strength
- user relevance
- evidence-derived summary

### WatchProfile

- beat
- entities/keywords
- included/excluded sources
- regions
- alert thresholds
- digest priority
- market symbols where relevant

### Digest

- schedule and coverage window
- selected story/observation IDs
- rendered text and citations
- model/provider metadata
- token/cost telemetry
- generation status
- delivery results

### Alert

- deterministic rule ID
- matching story/observation
- reason
- delivery channels/results
- cooldown/dedup state persisted across restarts

---

## 10. Beat design

### AI

Watch major model/product releases, model cards and technical reports, important open-source releases, AI regulation/government procurement, acquisitions/partnerships/pricing changes, and significant AI-platform security incidents.

Avoid alerting on every paper or repository release. Use the brief for breadth and alerts only for operationally important changes.

### Cybersecurity

Prioritize new CISA KEV entries, confirmed exploitation, emergency vendor advisories, high-impact vulnerabilities with credible exposure, major breaches/supply-chain compromises, ransomware campaigns, and widespread service outages.

Reuse concepts and possibly shared normalization logic from `fleet-cve-scanner`.

### Global politics

Prioritize conflict escalation or geographic expansion, sanctions, elections/government transitions, corroborated military movements, trade restrictions, energy/shipping disruptions, and cross-border policy changes.

Prefer changes and corroborated stories over a general news firehose.

### Healthcare regulation

Treat this as a first-class differentiator. Watch HHS/OCR, CMS, FDA, ONC, OIG, Federal Register rules/notices, HIPAA enforcement/guidance, healthcare cybersecurity directives, and Medicare/Medicaid operational changes.

Classify items as proposal, final rule, guidance, enforcement action, effective date/deadline, request for comment, or operational change.

### Markets

Use an explicit personal watchlist. Track material price/volatility moves, SEC filings, macro releases, interest-rate changes, commodities connected to political stories, crowd-market changes as evidence rather than truth, and cross-beat connections between stories and instruments.

Do not attempt to become a comprehensive trading terminal.

---

## 11. OpenRouter design

Use OpenRouter downstream of deterministic evidence selection:

```text
collect
→ normalize
→ persist
→ cluster
→ calculate changes
→ rank for the user
→ select evidence
→ LLM synthesis
→ validate citations
→ publish
```

Initial model roles:

- inexpensive model for classification/entity extraction/clustering assistance;
- stronger model once daily for the final brief;
- stronger model on demand for grounded chat;
- no multi-model council in production.

Requirements:

- one provider abstraction shared by digest and chat;
- explicit model configuration;
- token and estimated-cost telemetry;
- retry/backoff for transient errors;
- bounded prompts;
- JSON-schema output where structured output is needed;
- observation IDs in prompts;
- citation IDs validated against selected evidence;
- no published claim whose cited evidence is absent;
- transparent indication that selected public feed content is sent to OpenRouter.

---

## 12. Repository strategy

1. Preserve `review-fixes` as the research archive.
2. Add upstream as a remote for reference, not automatic merging.
3. Create a new development branch named `monitor-v1`.
4. Start from this fork so its experiment record remains reachable.
5. Remove forecast/swarm/resolver paths from the default runtime.
6. Keep research code behind an explicit optional mode or move it under `research/`.
7. Add the persistent event/story spine.
8. Port selected upstream collectors manually with fixtures and tests.
9. Adapt MCP, alerts, and briefing concepts.
10. Eventually make the UI and engine one Pythia-owned monorepo or pin the UI fork to a tested commit/image.

Do not continue relying indefinitely on a patch applied to an independently moving Osiris checkout.

Suggested future structure:

```text
apps/
  web/
services/
  engine/
    collectors/
    normalization/
    stories/
    ranking/
    briefing/
    delivery/
    api/
packages/
  contracts/
research/
  forecasting/
deploy/
  compose/
docs/
tests/
```

---

## 13. Implementation roadmap

### Phase 0 — Truth, safety, and reproducibility

Tasks:

- create `monitor-v1`;
- introduce `PYTHIA_MODE=monitor|research`;
- remove boot forecast and resolver activity from monitor mode;
- default engine binding to loopback/internal networking;
- add API bearer-token support for any remote API exposure;
- restrict CORS;
- update README, package description, and version;
- remove committed `.playwright-mcp` logs/snapshots and workstation-oriented artifacts;
- add GitHub CI;
- convert existing self-checks to the chosen test runner;
- add a Pythia engine Dockerfile;
- add one production Compose stack;
- add `/healthz` and `/readyz`;
- document secrets, backup, restore, deploy, and upgrade.

Acceptance criteria:

- `docker compose up -d` starts a healthy stack on a clean Linux host;
- only the web port is published;
- no forecast, swarm, ledger, or resolver call occurs in monitor mode;
- OpenRouter key is unavailable to the web container;
- all tests pass in CI;
- restart preserves configuration and data.

### Phase 1 — Trustworthy event spine

Tasks:

- SQLite schema and migrations;
- Source/FeedRun/Observation/Story tables;
- stable IDs;
- source timestamps and URLs;
- fix coordinate-zero handling;
- adapter contract;
- recorded JSON fixtures for retained feeds;
- health/freshness reporting;
- durable event history;
- first-pass deduplication and change detection;
- atomic writes and graceful shutdown.

Acceptance criteria:

- identical source records keep the same identity across restart;
- feed error vs healthy-empty is visible;
- `since` uses durable timestamps;
- every observation has provenance;
- schema changes fail the relevant fixture test;
- current and historical feed health are queryable.

### Phase 2 — Personal relevance and briefing

Tasks:

- five initial beat profiles;
- entity/keyword/region/watchlist configuration;
- deterministic ranking;
- story clustering;
- new/changed/escalating/resolved calculations;
- citation-aware OpenRouter synthesis;
- scheduled morning brief;
- digest persistence/history;
- delivery adapters;
- cost telemetry.

Acceptance criteria:

- the brief explicitly covers a time window;
- every factual bullet links to evidence;
- unchanged stories do not masquerade as new;
- missing feeds produce a coverage warning;
- duplicate observations do not create duplicate brief bullets;
- a failed provider call does not overwrite the previous successful brief.

### Phase 3 — Alerts, dashboard, and agent access

Tasks:

- durable deterministic alert rules;
- persisted cooldown/deduplication;
- dashboard organized around Now / Changed / Watch / Sources;
- story timeline and source drill-down;
- feed-health panel;
- grounded chat over selected stored evidence;
- MCP tools: `changes_since`, `get_story`, `search_observations`, `feed_health`, `latest_brief`, and `ask_pythia`;
- safe optional webhooks/notifications.

Acceptance criteria:

- restart does not duplicate alerts;
- chat returns citations;
- feed failure is visible in the dashboard;
- MCP payloads are bounded;
- webhook destinations are validated against SSRF/private-network risks.

### Phase 4 — Selective coverage expansion

Only after the first five beats are useful.

Candidate upstream adapters include CISA KEV, FAA status, IODA, wastewater, NHC/GDACS, SEC EDGAR, selected market/odds sources, selected regulatory sources, and cameras on demand if useful.

Every added feed must have a named user need, source terms reviewed, an adapter fixture, health/freshness behavior, a deduplication identity, and an explicit alert/digest role.

---

## 14. Current deployment audit

### `run-all.sh`

Not suitable for homelab production because it assumes a desktop workstation; uses `open`, `lsof`, `pkill`, and `$HOME/osiris`; assumes Ollama despite OpenRouter usage; runs development servers; exposes both services; and has no durable internal scheduler or container health model.

### Existing Osiris Compose

Not suitable as the final Pythia deployment because it omits the Pythia engine, assumes an external `umami_default` network, publishes multiple services, lacks health checks and application authentication, includes services not needed for Monitor v1, and documents a prebuilt `image:` configuration absent from the inspected Compose file.

Replace it with a Pythia-owned Compose stack.

---

## 15. Cleanup and documentation debt

- README currently says local/Ollama/no cloud while this fork uses OpenRouter.
- README still markets forecasting as the core capability.
- `pyproject.toml` and `engine/__init__.py` describe the old oracle.
- `STATE.md` contains valuable research but also workstation paths and operational history.
- `.playwright-mcp` logs and snapshots are committed.
- Default branch name `review-fixes` communicates a temporary snapshot.
- There is no public deployment/architecture document for the monitor pivot.
- No GitHub Actions test/build workflow exists.
- Current version `0.3.0` does not communicate the strategic change.

Preserve historical documents, but clearly label them as archived research.

---

## 16. Unanswered interview questions

These should be answered before choosing notification and access implementation:

1. **Delivery:** Telegram, email, Discord, ntfy, dashboard only, or a combination?
2. **Alert policy:** urgent alerts at any time, or mostly morning/evening batches?
3. **Homelab access layer:** Tailscale, Authentik, Cloudflare Tunnel, Nginx Proxy Manager, Traefik, or something else?
4. **First supported host:** Unraid or Proxmox?

Useful later questions:

5. Which market symbols, sectors, commodities, and macro indicators belong in the first watchlist?
6. Which regions/countries matter most for global-politics monitoring?
7. Should healthcare regulation be US-only initially?
8. Desired data retention: 30 days, one year, or indefinite?
9. Preferred morning-brief time and timezone?
10. Maximum acceptable monthly OpenRouter budget?

---

## 17. Resume checklist for another computer

1. Clone the fork.
2. Check out `review-fixes`.
3. Read this document completely.
4. Read `STATE.md` for the experiment record.
5. Answer the questions in Section 16.
6. Create `monitor-v1` from the agreed archive point.
7. Record the answers as a short decision log before implementation.
8. Begin with Phase 0; do not add feeds or UI features first.
9. Verify with tests that monitor mode makes zero forecast/resolver calls.
10. Commit at phase boundaries.

Suggested start:

```bash
git clone https://github.com/boostedchaos/Pythia.git
cd Pythia
git switch review-fixes
git switch -c monitor-v1
```

Before coding, inspect whether `review-fixes` changed after this plan was recorded and reconcile deliberately.

---

## 18. One-paragraph continuation prompt

> Read `PYTHIA-MONITOR-V1-PLAN.md` and `STATE.md` completely. We are converting the archived Pythia forecasting fork into a private, OpenRouter-backed homelab intelligence monitor for AI, cybersecurity, global politics, healthcare regulation, and markets. Preserve the forecasting experiment as history, but implement no forecast, swarm, ledger, or resolver activity in monitor mode. Start by confirming the unanswered deployment/delivery decisions, auditing current branch drift, and executing Phase 0 with tests and a portable Docker Compose stack.

---

## 19. Bottom line

The valuable part of PYTHIA is not its claim to predict the world. It is the beginning of a system that can continuously watch many domains, retain evidence, identify changes, and brief a human or another agent.

Monitor v1 should optimize for trust, provenance, change detection, personal relevance, low operational burden, safe homelab deployment, honest OpenRouter use, and small high-value outputs.

Coverage count, visual spectacle, persona count, and forecast volume are not success metrics.
