# PYTHIA Monitor v1 — Plan of Record

**Status:** Phase 0 COMPLETE and verified on the target host. Phases 0.5–4 specified, not started.
**Originally recorded:** 2026-08-28 (planning only)
**Revised:** 2026-08-28 (evening) — after a code audit, a homelab siting decision, and the Phase 0 build
**Branch:** `monitor-v1` (Phase 0 = commit `5fcd8f3`)
**Archive branch:** `review-fixes` — the forecasting experiment's record. Do not rewrite it.

---

## 0. How this document changed

The first draft of this plan was written before anyone checked its claims against the code or
picked a host. Three things happened after it:

1. **Its audit was verified.** Eight of its findings were checked line by line. All eight were real.
   No invented defects. That is unusual and it means Section 5 can be trusted.
2. **Its roadmap was wrong in one important way.** It deferred adding feeds to Phase 4 — but the
   existing feeds cannot answer three of the five chosen beats. See §5.10.
3. **Phase 0 was built and verified on real hardware.** See §3.

Everything below reflects the current state, not the original intent.

---

## 1. Executive decision (unchanged, now with a host)

PYTHIA is a **private, always-on homelab intelligence service**, not a forecasting oracle.

> Tell me what changed in the parts of the world I care about, why it matters, and show me the receipts.

**Beats:** AI · cybersecurity · global politics · healthcare regulation · markets.

**It is not** a predictor, a persona council, a single world-health score, a public multi-user
service, a trading terminal, or anything that takes autonomous action on an LLM's conclusion.

---

## 2. Decisions of record

Everything here was decided deliberately. Do not relitigate without a reason.

| Decision | Choice | Date | Why |
|---|---|---|---|
| Forecasting | **Retired.** Archived behind `PYTHIA_MODE=research` | 2026-07-08, enforced 08-28 | Ledger forensics + research: the architecture cannot reach decision-grade skill |
| Host | **Debian 13 VM on Proxmox node `pve2`** | 2026-08-28 | Midgard has no Compose plugin; Proxmox gives `vzdump` backups; Midgard `:8088` is SearXNG |
| Osiris | **Dropped.** Pythia fetches feeds directly | 2026-08-28 | A Next.js globe app run purely as an HTTP proxy; blocks the AI + healthcare beats; hand-patched fork |
| Delivery | **ntfy** | 2026-08-28 | No bot tokens, no SMTP, phone + desktop, fits the homelab |
| Remote access | **Tailscale** + bearer token | 2026-08-28 | No open ports, no reverse proxy, no certs |
| Retention | **1 year, then prune** | 2026-08-28 | Deep enough to see a story develop; bounded database |
| Alert policy | **Quiet hours 22:00–07:00**, a small urgent set may break through | 2026-08-28 | Signal without 3am buzzing |
| LLM budget | **Under $5/month** | 2026-08-28 | Clustering and change detection stay deterministic — better engineering as well as cheaper |
| Markets watchlist | **Broad macro defaults**, no personal holdings | 2026-08-28 | Useful on day one; assumes nothing about what Kyle owns |
| Brief schedule | **07:00 America/Chicago** | assumed | Matches the retired Windows digest task. Change in config if wrong. |
| Healthcare scope | **US only** for v1 | assumed | HHS/CMS/FDA/ONC/OCR are US bodies |
| Build autonomy | Build + test + deploy + commit. **Never push. Never touch another homelab host.** | 2026-08-28 | Kyle reviews the branch before it reaches GitHub |

---

## 3. Phase 0 — COMPLETE (commit `5fcd8f3`)

### 3.1 The host, as built

| Item | Value |
|---|---|
| Guest | VM **107**, name `pythia`, on node **pve2** (192.168.0.111), cluster `asgard` |
| Address | **192.168.0.28** (DHCP — a UniFi fixed-IP reservation is still TODO; MAC `BC:24:11:CF:02:8F`) |
| OS | Debian 13 (trixie) genericcloud, cloud-init |
| Size | 4 GB RAM · 2 vCPU · 32 GB on `local-lvm` |
| Boot | `onboot: 1`, `startup: order=4` |
| Runtime | Docker **29.7.2**, Docker Compose **v5.5.0** |
| Login | `ssh -i ~/.ssh/id_ed25519_pythia pythia@192.168.0.28` (passwordless sudo) |
| Repo on host | `~/pythia`, stack in `~/pythia/deploy/compose` |
| Headroom left on pve2 | ~20 GB RAM, ~125 GB `local-lvm` |

### 3.2 Cluster quorum — tested, not assumed

The homelab docs warn that a QDevice can report success while casting zero votes, which would
mean guests do not autostart after a reboot. **Tested 2026-08-28 by rebooting pve2:**

- pve stayed quorate on **2 of 3 votes** while pve2 was gone.
- `/etc/pve` stayed **writable** (a read-only `/etc/pve` is the failure signature).
- Both nodes show the QDevice flag `V` (voting), not `NV`.
- Guests auto-started on return; Hermes reachable. Total outage ~75 seconds.

**Limit, stated plainly:** only one direction was tested — pve surviving without pve2. Rebooting
pve was not done because it takes TrueNAS and its USB drive shelf down. The mechanism is symmetric
and both nodes vote, but the reverse was not measured.

**Known asymmetry:** the tie-breaker is `lowest node ID` = **pve**. In a network split where both
nodes still reach the Pi witness, pve wins and **pve2 loses quorum** — Pythia would pause until the
link heals. This is a split-brain case, not a node-down case, and it is acceptable. Know it exists.

### 3.3 What Phase 0 shipped

**Operating mode.** `PYTHIA_MODE=monitor|research`, default `monitor`. An unrecognised value fails
**closed** to monitor — a typo can never re-enable forecasting. In monitor mode: no boot forecast,
no oracle loop, the resolver is never imported, and `run_prediction()` raises at the callee rather
than relying on every caller remembering. `/predict`, `/resolve`, `/loop`, `/history` return **409**.

**Security defaults.** Binds `127.0.0.1` (was `0.0.0.0`). CORS is an explicit allowlist, empty by
default (was `["*"]`). Optional `PYTHIA_API_TOKEN` bearer gate with a constant-time compare;
`/healthz` and `/readyz` stay open so an orchestrator never needs the secret.

**Intake correctness.**

- Coordinate-zero fixed. `d.get("lat") or d.get("latitude")` silently dropped a valid `0`.
- Feed health is now first-class: each fetch returns a FeedRun with status, HTTP code, counts,
  error and last-success time. `GET /feeds/health` exposes it. A dead feed and a quiet feed are
  no longer the same thing.
- `asyncio.gather(return_exceptions=True)` — one raising feed used to zero all 23.

**Honest clocks.** `last_run_ms` only moved on a forecast, so `/agent/view` was permanently stale
in monitor mode. Added `world_refreshed_at`, `last_successful_feed_at`, and
`forecast_generated_at` (research only). `CONFIG.summary()` no longer advertises swarm/horizon
settings in monitor mode.

**Lifecycle.** Background tasks are cancelled and awaited on shutdown.

**Deployment.** Non-root Dockerfile (uid 10001), `/data` volume, HEALTHCHECK on `/readyz`.
Compose stack on a private bridge, published to a *named* interface (loopback default), `read_only`,
`cap_drop: ALL`, `no-new-privileges`, log rotation.

**CI.** Tests, a dedicated monitor-mode gate, and an image build that boots the container and
greps its log for forecast activity — with a canary line proving the grep actually fires.

**Housekeeping.** 31 committed `.playwright-mcp` artifacts removed and gitignored. Version 0.3.0 →
0.4.0. Package and module docstrings describe the monitor, not the oracle.

### 3.4 Evidence — what was actually observed

Not "the tests pass." These are readings from the running container on 192.168.0.28.

| Claim | Evidence |
|---|---|
| Coordinate-zero survives the real pipeline | A Null Island event came back through `/agent/events` as `lat=0.0 lng=0.0` |
| Feed health distinguishes broken from quiet | `/feeds/health`: `{healthy: 10, empty: 12, error: 1}` with the one 503 named |
| `/readyz` refuses to lie | 503 with all 23 feeds dead; 200 once one answered |
| Forecast routes refuse | All four returned `409 forecasting is retired` |
| No forecast work runs | Log grep clean — **and the grep was proven against a canary** |
| No ledger writes | `/data` empty |
| Survives a reboot | VM rebooted (confirmed by **boot_id change**, not by assumption); container auto-started healthy; volume persisted |
| Container is non-root | `uid=10001(pythia)` |

**Every fix was proven by reverting it and confirming the test failed**, then restoring it. Three
canaries were run; all three fired.

**Two bugs were found in Phase 0's own work and fixed:** `/readyz` reported "ready" while all 23
feeds were dead, and the log checker matched the word `swarm_models` in a config dump. Both now
have tests.

### 3.5 Phase 0 gaps — carry these forward

1. **No real feed source has ever been tested.** The healthy path was proven with a fake feed
   server written for the test. This is exactly the "verify with the real producer" trap. Phase 1
   must exercise real sources.
2. **DHCP, not reserved.** Add a UniFi fixed-IP reservation for MAC `BC:24:11:CF:02:8F`.
3. **No backup job yet.** `vzdump` for VM 107 is not scheduled. The history *is* the product.
4. **Not pushed.** `monitor-v1` exists only on the Mac.
5. **Tailscale not installed** on the VM.
6. **`daily-digest.py`, `run-all.sh`, `PYTHIA.command`, `PYTHIA.app`, `integrations/osiris/`** are
   all workstation-era artifacts that Phase 0.5/1 will replace or delete.

---

## 4. The forecasting experiment — conclusion and preservation

The fork built a genuinely multi-model forecasting council with persistence, resolution and Brier
scoring. It accumulated 1,009 forecasts and 384 resolutions, and it failed:

- severe over-forecasting;
- ~50% of outcomes unresolvable;
- no genuine anticipatory hits in the reviewed sample;
- a trivial base-rate forecast beat it by roughly **4×**;
- inconsistent LLM-judge outcomes on similar statements;
- prompt-level calibration did not materially help.

**Preservation policy.** Keep `review-fixes` and the ledger intact. Do not delete the record. Do not
use the old judge labels to weight any production decision. Do not import upstream's Brier-weighted
persona consensus.

**If forecasting is ever revisited**, it is a separate research module built on: externally defined
resolvable questions (e.g. Metaculus), retrieval at forecast time, objective external resolution,
crowd/base-rate benchmarks, time-separated evaluation, and explicit shrinkage. Not the old pipeline.

---

## 5. Audit findings — status

All eight original findings were verified in code before any were fixed.

| # | Finding | Status |
|---|---|---|
| 5.1 | Forecasting not actually retired (boot forecast, resolver on an interval) | **FIXED** — Phase 0 |
| 5.2 | Unsafe default exposure (`0.0.0.0`, CORS `*`, no auth) | **FIXED** — Phase 0 |
| 5.3 | Feed failures invisible downstream | **FIXED** — Phase 0 (`/feeds/health`) |
| 5.4 | Event identity not durable (random IDs, `title[:80]` dedup, memory-only) | **OPEN** — Phase 1 |
| 5.5 | Coordinate-zero dropped | **FIXED** — Phase 0, verified end to end |
| 5.6 | World-brief selection biased by raw event count | **OPEN** — Phase 2 |
| 5.7 | Digest is a snapshot, not change intelligence | **OPEN** — Phase 0.5 |
| 5.8 | Stale API timestamps | **FIXED** — Phase 0 |
| 5.9 | Lifecycle/persistence weaknesses | **PARTLY FIXED** — shutdown + gather done; persistence in Phase 1 |

### 5.10 New finding — the feeds do not match the beats

**This is the most important addition to this plan.** The original roadmap deferred feed work to
Phase 4. But of the five chosen beats, the inherited 23 feeds cover:

| Beat | Coverage today |
|---|---|
| Global politics | Good — GDELT, conflicts, news |
| Markets | Thin — price quotes only |
| Cybersecurity | Weak — one generic feed |
| **AI** | **None** |
| **Healthcare regulation** | **None** — the "health" feed is disease outbreaks, not FDA/CMS/HIPAA |

Building the storage spine, ranking and briefing over data that cannot answer three of five
questions is wasted work. **Feed acquisition moves into Phase 1.**

### 5.11 New finding — market events can never be deduplicated

Market events are titled `"BTC: 65432 (+1.2%)"`. The price is inside the dedup key, so every fetch
produces a brand-new event. Change detection on markets is structurally impossible until the
identity is `(symbol)` with the price as an attribute. Phase 1.

### 5.12 New finding — container-hostile config

`engine/config.py` reads `~/.hermes/.env` for credentials and defaults `LLM_BASE_URL` to Ollama
at `localhost:11434`. Neither exists in a container: a fresh deploy silently points at nothing.
Phase 0.5 must make configuration explicit and container-first.

---

## 6. Success measurement — the thing the first draft lacked

The forecasting version died **because it was measured**. The monitor must be measurable too, or
"a good monitor" and "a monitor that sounds good" are indistinguishable.

**The instrument.** Every brief bullet carries an observation ID. A `POST /feedback` endpoint (and
a one-key action in the dashboard) records one of three verdicts per bullet:

- `useful` — told me something I would have acted on or wanted to know
- `known` — true, but I already knew it
- `noise` — should not have been in the brief

**Plus a misses log.** A markdown file where Kyle records anything significant in his beats that
the brief failed to surface. Misses are the number that matters most and the only one the system
cannot collect by itself.

**Targets after four weeks of daily briefs:**

| Metric | Target |
|---|---|
| `useful` share of bullets | ≥ 40% |
| `noise` share of bullets | ≤ 20% |
| Recorded misses | ≤ 2 per week |
| Alerts fired | ≤ 5 per week, ≥ 60% rated useful |

**Read these against the population, not in the abstract.** A ratio survives a change in brief
length; a raw count does not. Store the number of bullets alongside every score, and refuse a
week-over-week comparison when the beat set, the feed set, or the ranking code changed — name the
change instead of publishing the delta.

---

## 7. Roadmap

### Phase 0 — Truth, safety, reproducibility ✅ DONE

See §3. Acceptance criteria met and evidenced.

### Phase 0.5 — Cited delta digest (NEW — the fastest path to value)

The original plan went straight from safety work into a full persistence-and-ranking spine. This
phase inserts a usable product first, so the idea is proven before the machine is built.

**Goal:** a daily brief that says what is **NEW**, **CHANGED** and **GONE** since yesterday, with a
source link on every line, covering all five beats.

Tasks:

- SQLite (WAL) with stable observation identity — the minimum spine, not the full model.
- Direct feed adapters for the beats with **zero** coverage: AI and US healthcare regulation
  (see §8). Enough to make the brief honest, not the full catalogue.
- Deterministic delta computation: NEW / CHANGED / GONE by comparing today's observations against
  yesterday's stored set. **No LLM in the change-detection path.**
- One LLM call per day that **rewrites selected evidence** — it never selects it.
- Citation validation: every published claim's cited observation ID must exist in the evidence
  that was actually sent. A claim citing something absent blocks publication.
- Container-first configuration (§5.12): explicit env, no `~/.hermes`, no Ollama default.
- ntfy delivery of the brief.
- Retire `daily-digest.py`, `run-all.sh`, `PYTHIA.command`, `PYTHIA.app`.

Acceptance criteria:

- the brief names its exact coverage window;
- every factual bullet carries a working source URL and an observation ID;
- an unchanged story from yesterday never appears under NEW;
- a failed provider call leaves yesterday's brief intact rather than overwriting it;
- a feed outage produces a visible coverage warning in the brief itself;
- a synthetic run with a planted duplicate produces one bullet, not two;
- **a planted fabricated citation is rejected** — prove the validator fires.

**Then stop and use it for two weeks** before building Phase 1. Collect the §6 measurements.

### Phase 1 — Trustworthy event spine

- Full Source / FeedRun / Observation / Story schema and migrations.
- Stable identity order: upstream ID → canonical URL → source-specific natural key → content
  fingerprint. Fixes §5.4 and §5.11.
- Durable `first_seen` / `last_seen` / revisions; `since` becomes meaningful across restarts.
- Recorded JSON fixtures per adapter; a schema change must fail its fixture test.
- Story clustering (deterministic; embeddings only if it clears its cost against the budget).
- Remaining beat feeds: cybersecurity depth, markets, politics (see §8).
- 1-year retention with a pruning job.
- Atomic writes everywhere.

Acceptance criteria:

- an identical source record keeps the same identity across a restart;
- a market instrument produces one story with a price history, not N events;
- every observation has provenance;
- **the checked-count moves** — when a feed is added, the number of feeds the health report says
  it checked must go up. A silent skip looks exactly like a pass.

### Phase 2 — Personal relevance and ranking

- Beat profiles, entity/keyword/region config, macro markets watchlist.
- Deterministic ranking: severity × recency × source reliability × novelty × relevance ×
  corroboration, with **per-beat and per-source budgets** so one noisy feed cannot starve the rest
  (fixes §5.6).
- Escalation states derived from evidence, not from an LLM's opinion.
- `POST /feedback` and the misses log from §6.
- Cost telemetry with the sub-$5/month ceiling enforced.

### Phase 3 — Alerts, dashboard, agent access

- Deterministic alert rules with persisted cooldown/dedup; quiet hours 22:00–07:00 with a small
  documented urgent-override set.
- Dashboard organised as Now / Changed / Watch / Sources, plus a feed-health panel.
- Grounded chat over stored evidence, with citations.
- MCP tools: `changes_since`, `get_story`, `search_observations`, `feed_health`, `latest_brief`,
  `ask_pythia`.
- Tailscale binding + bearer token turned on.

Acceptance criteria:

- a restart never re-fires an alert that already fired;
- chat answers carry citations that resolve;
- MCP payloads are bounded;
- quiet hours are proven by a test that advances the clock.

### Phase 4 — Selective coverage expansion

Only once the first five beats are demonstrably useful by the §6 numbers. Every added feed needs a
named user need, reviewed terms, a fixture, health behaviour, a dedup identity, and an explicit
digest/alert role. Coverage count is not a success metric.

---

## 8. Feed acquisition (Phase 0.5 / Phase 1)

The beats with no coverage come first. **Every source below is a candidate, not a verified fact.**
Before adopting any of them, confirm: it is reachable, it is keyless or the key is free and stored
correctly, its terms permit this use, and its schema is captured in a fixture. Record what you
verified. Do not assume a source is keyless because this document lists it.

**AI (zero coverage today).** Vendor engineering/release blogs via RSS; arXiv `cs.AI`/`cs.LG`
listings; major open-weights release announcements; AI items in the US Federal Register. Alert only
on operationally important changes, never on every paper.

**Healthcare regulation, US (zero coverage today).** Federal Register API filtered to HHS, CMS, FDA,
ASTP/ONC and OIG; openFDA; the HHS OCR breach portal; CMS newsroom. Classify each item as proposal,
final rule, guidance, enforcement action, effective date, request for comment, or operational change
— that classification is most of the value.

**Cybersecurity (weak today).** CISA KEV; CISA advisories; NVD; major vendor advisory feeds; public
breach notifications. Prioritise confirmed exploitation and credible exposure over CVE volume.
Consider sharing normalisation with `fleet-cve-scanner`.

**Global politics (good today).** Keep GDELT and conflict/news feeds. Add humanitarian and official
advisory sources. Prefer corroborated change over a firehose.

**Markets (thin today).** Broad macro defaults only: major indices, rates/treasury yields, oil, gold,
BTC. SEC EDGAR filings for named entities. **No personal holdings, and no number in a brief that
does not name the source it came from.**

---

## 9. Target data model

**Source** — id, display name, class, canonical domain, reliability tier, expected cadence,
enabled state, terms notes.

**FeedRun** — source id, start/complete, status (`healthy|empty|stale|error`), HTTP result,
received/accepted/rejected counts, source data timestamp, last success, safe error summary.
*(Shipped in memory in Phase 0; persisted in Phase 1.)*

**Observation** — stable id, source id + upstream id, canonical URL, source and fetch timestamps,
title, body, entities, geography, beat, normalised severity, content hash, supersedes link.

**Story** — stable id, canonical title, first seen / last observed / last changed, status
(`new|active|escalating|de-escalating|resolved|stale`), linked observations, entities, geography,
beats, corroboration strength, relevance, evidence-derived summary.

**WatchProfile** — beat, entities/keywords, included/excluded sources, regions, alert thresholds,
digest priority, market symbols.

**Digest** — schedule, coverage window, selected ids, rendered text, citations, model metadata,
token/cost telemetry, status, delivery results.

**Alert** — rule id, matched story, reason, channels/results, cooldown state persisted across
restarts.

**Feedback** *(new, from §6)* — bullet id, observation ids, verdict, timestamp.

---

## 10. LLM design

Deterministic first, LLM last:

```
collect → normalize → persist → cluster → compute deltas → rank → select evidence
        → LLM synthesis → validate citations → publish
```

- One provider abstraction shared by brief and chat. OpenRouter.
- A cheap model for any classification that genuinely needs one; a stronger model once daily for
  the brief; a stronger model on demand for chat. **No council, ever.**
- Structured output with JSON schema where structure matters.
- Observation IDs go into the prompt; cited IDs are validated against what was sent.
- **No published claim may cite evidence that was not in the selection.** This is a hard gate.
- Token and cost telemetry, with the monthly ceiling enforced in code.
- Retry with backoff; bounded prompts.
- Be transparent that selected public feed content is sent to OpenRouter.

---

## 11. Upstream divergence

Upstream (`jangles-byte/Pythia`) has moved far ahead — roughly 48 commits, ~48 feeds, MCP, signal
rules, Morning Brief scheduling, webhooks, watchlists, and a much larger forecast surface.
*(Commit counts were reported in the first draft and have not been re-verified since.)*

**Do not merge or rebase.** Upstream doubled down on the architecture this fork disproved, and much
of its surface is forecast-dependent.

**Harvest selectively, after review:** MCP transport and tool packaging; alert and notification
concepts; Morning Brief scheduling; bounded feed latency; individual source adapters; feed-health
work; watchlist concepts independent of forecasts.

**Never import:** Brier-weighted persona voting; self-judging resolution; the global 1–100 health
score; forecast-driven watchlists; feeds added purely for coverage; webhooks without SSRF and
private-network validation.

---

## 12. Repository strategy

- `review-fixes` = research archive. Preserve.
- `monitor-v1` = the build branch.
- Forecast code stays reachable only via `PYTHIA_MODE=research`; move it under `research/` when
  convenient.
- Add upstream as a read-only remote for reference, never for automatic merging.
- Delete the Osiris overlay (`integrations/osiris/`) once direct feeds land.

Target structure:

```
services/engine/{collectors,normalization,stories,ranking,briefing,delivery,api}/
packages/contracts/
research/forecasting/
deploy/compose/
apps/web/
docs/  tests/
```

---

## 13. Operational runbook

**Deploy.**

```bash
rsync -az --delete -e "ssh -i ~/.ssh/id_ed25519_pythia" \
  --exclude .git --exclude .venv --exclude __pycache__ --exclude "deploy/compose/.env" \
  ./ pythia@192.168.0.28:~/pythia/
ssh -i ~/.ssh/id_ed25519_pythia pythia@192.168.0.28 \
  'cd ~/pythia/deploy/compose && docker compose up -d --build'
```

**Health.** `curl http://192.168.0.28:8088/healthz` · `/readyz` · `/feeds/health`
*(loopback-bound by default — run these on the VM, or set `PYTHIA_PUBLISH_ADDR` to the Tailscale IP.)*

**Secrets.** `~/pythia/deploy/compose/.env` on the VM only. Gitignored. Never in the image.

**Backup — TODO.** Schedule `vzdump` for VM 107 on pve2. The accumulated history is the product;
until this exists, a lost VM is a lost product.

**Restore.** `qmrestore` the vzdump, boot, `docker compose up -d`.

---

## 14. Open questions

Answered on 2026-08-28: host, Osiris, delivery, access layer, retention, alert policy, budget,
markets watchlist, autonomy. Recorded in §2.

Still open:

1. Which **regions/countries** matter most for global politics? *(Ships as a config file with a
   broad default until answered.)*
2. Confirm the **07:00 America/Chicago** brief time.
3. Confirm **US-only** healthcare regulation for v1.
4. Should the brief also land somewhere readable later — a file, Obsidian, email archive — or is
   ntfy plus the dashboard enough?

---

## 15. Bottom line

The valuable part of PYTHIA was never its claim to predict the world. It is a system that watches
many domains continuously, keeps the evidence, notices what changed, and briefs a human or another
agent.

Optimise for: trust, provenance, change detection, personal relevance, low operational burden, safe
homelab deployment, honest LLM use, and small high-value outputs.

Coverage count, visual spectacle, persona count and forecast volume are not success metrics.
The numbers in §6 are.
