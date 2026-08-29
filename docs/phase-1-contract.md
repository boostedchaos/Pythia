# Phase 1 build contract (architect-issued, 2026-08-29)

Builds on docs/phase-0.5-contract.md. Same hard rules. Plan of record: PYTHIA-MONITOR-V1-PLAN.md
§7 Phase 1, §5.4, §5.11, §9.

## Schema v2 (migration; add schema_version table, current=2; migrate v1 in place, no data loss)

- sources(source_id PK, display_name, beat, kind, canonical_domain, enabled INT, terms_note)
  — upserted from adapter modules at boot. Adapters gain DISPLAY_NAME and CANONICAL_DOMAIN.
- feed_runs(id PK AUTOINC, source_id, started_ms, completed_ms, status, http_status,
  received, accepted, error) — one row per adapter run, persisted by collect. /feeds/health
  serves the LATEST persisted run per source after a restart (no more memory-only health).
- revisions(obs_id, ts_ms, content_hash, changed_json) — appended on every CHANGED upsert.
  changed_json = {field: [old, new]} for title/summary/extra keys. Price history for an
  instrument = its revisions of extra["price"].
- stories(story_id PK, story_key UNIQUE, beat, source_id, title, first_seen_ms,
  last_changed_ms, obs_count) + story_observations(story_id, obs_id).

## Story identity — deterministic, no similarity scoring in v1 (deliberate)

- KIND=="snapshot" source: story_key = f"{source_id}|{upstream_id}" — a market instrument,
  a KEV CVE, an advisory country is ONE story across all time; its price/level history lives
  in revisions. This is the §5.11 fix.
- KIND=="stream" source: story_key = obs_id (1:1). Cross-source clustering is Phase 2+.
- Stories update inside the same transaction as the observation upsert (atomic).

## Retention

RETENTION_DAYS env, default 365. A daily prune job (rides the existing schedule task) deletes
observations, revisions, feed_runs, snapshot_presence and story links older than the cutoff
(story row goes when its last obs goes). Briefs are KEPT. Prune runs in one transaction and
logs counts deleted.

## Identity order (unchanged from 0.5, now stated fully)

upstream_id → canonical URL → normalized title. Content fingerprint stays the CHANGE detector
(content_hash), never the identity.

## API additions (small)

GET /stories?beat=&limit= and GET /story/{story_id} (metadata + linked obs ids + revisions).
Read-only, token rules as existing routes.

## Acceptance (plan §7 Phase 1) — build the tests for these

1. An identical source record keeps the same obs_id AND first_seen across a process restart
   (test: two Store() instances on one db file; VM restart check is the architect's job).
2. A market instrument over N fetches with moving price = ONE story, revisions hold the
   price history.
3. Every observation has provenance: source_id, url, first_seen_ms, last_seen_ms all
   non-null — asserted over the whole db in a test.
4. Adding a feed moves the checked-count: /feeds/health feed_count and the sources table both
   grow; a silent skip must be distinguishable (test with a registry of n then n+1 adapters).
