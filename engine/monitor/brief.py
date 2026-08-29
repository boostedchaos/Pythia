"""The daily cited delta brief.

Order of operations (plan §10) — deterministic first, LLM last:

    delta -> deterministic selection -> evidence pack -> ONE LLM rewrite
          -> citation validation (hard gate) -> render -> publish

The LLM never chooses what goes in the brief and never emits a URL. It rewrites an
evidence pack that was already selected by code, and every bullet it returns must
cite an obs_id that was in the pack that was actually SENT. Anything else is not
published: the previous brief stays the latest one.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from ..config import CONFIG, HTTPX_VERIFY, OPENROUTER_HEADERS
from . import delta as delta_mod
from .models import BEATS
from .store import Store, get_store, now_ms

log = logging.getLogger("pythia.monitor.brief")

MAX_BULLETS_PER_BEAT = 8
DEFAULT_WINDOW_MS = 24 * 60 * 60 * 1000

_SYSTEM = (
    "You rewrite pre-selected monitoring evidence into a terse daily brief. "
    "You do NOT select, rank, add, infer or speculate: every bullet must restate one or "
    "more of the supplied observations and nothing else. Never invent an observation id. "
    "Never write a URL — the renderer attaches those. "
    "Return JSON only: {\"bullets\": [{\"beat\": str, \"text\": str, \"obs_ids\": [str]}]}. "
    "`beat` must be copied from the evidence. `text` is one sentence, under 40 words, "
    "leading with what changed."
)

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "brief_bullets",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["bullets"],
            "properties": {
                "bullets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["beat", "text", "obs_ids"],
                        "properties": {
                            "beat": {"type": "string"},
                            "text": {"type": "string"},
                            "obs_ids": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                }
            },
        },
    },
}


class CitationError(Exception):
    """A bullet cited evidence that was not in the pack that was sent."""


class LLMError(Exception):
    """The rewrite call did not produce usable JSON."""


# ── deterministic selection ────────────────────────────────────────────────────

def select(delta: dict, per_beat: int = MAX_BULLETS_PER_BEAT) -> "list[dict]":
    """CHANGED first, then NEW, each by recency; GONE appended per beat. Cap per beat.

    This is the only thing that decides what the brief covers. It is pure, it is
    testable, and no model participates in it."""
    tagged: list[dict] = []
    for row in delta.get("changed", []):
        tagged.append({**row, "kind": "changed", "_sort": row.get("changed_at_ms") or 0})
    for row in delta.get("new", []):
        tagged.append({**row, "kind": "new", "_sort": row.get("first_seen_ms") or 0})
    for row in delta.get("gone", []):
        tagged.append({**row, "kind": "gone", "_sort": row.get("last_seen_ms") or 0})

    order = {"changed": 0, "new": 1, "gone": 2}
    tagged.sort(key=lambda r: (order[r["kind"]], -r["_sort"]))

    out: list[dict] = []
    per: dict[str, int] = {}
    for row in tagged:
        beat = row.get("beat") or "other"
        if per.get(beat, 0) >= per_beat:
            continue
        per[beat] = per.get(beat, 0) + 1
        out.append(row)
    return out


def evidence_pack(selected: "list[dict]") -> "list[dict]":
    """Exactly what the model is allowed to see. `obs_id` is the citation key."""
    pack = []
    for row in selected:
        item = {
            "obs_id": row["obs_id"],
            "beat": row.get("beat") or "other",
            "kind": row["kind"],
            "title": row.get("title") or "",
            "summary": (row.get("summary") or "")[:600],
            "source": row.get("source_id") or "",
        }
        if row["kind"] == "changed":
            item["what_changed"] = _describe_change(row)
        pack.append(item)
    return pack


def _describe_change(row: dict) -> str:
    """What a reader needs in order to know the change was real. Attributes only —
    the store keeps the current values, so this names the fields that carry them."""
    try:
        extra = json.loads(row.get("extra_json") or "{}")
    except (ValueError, TypeError):
        extra = {}
    if extra:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(extra.items())[:6])
        return f"attributes now: {parts}"
    return "title or summary was updated by the source"


# ── the one LLM call ───────────────────────────────────────────────────────────

async def rewrite_with_llm(pack: "list[dict]", model: str, base_url: str, api_key: str,
                           timeout: int = 120) -> dict:
    """One chat completion. Returns {"bullets": [...], "usage": {...}, "model": str}.

    Any transport, status, or parse failure raises LLMError — the caller's failure
    path is identical to the citation gate's, because both mean "do not publish"."""
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps({"evidence": pack}, ensure_ascii=False)},
        ],
        "response_format": _RESPONSE_FORMAT,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if "openrouter" in base_url:
        headers.update(OPENROUTER_HEADERS)
    try:
        async with httpx.AsyncClient(verify=HTTPX_VERIFY, timeout=timeout) as c:
            r = await c.post(f"{base_url.rstrip('/')}/chat/completions",
                             json=payload, headers=headers)
            if r.status_code >= 400:
                raise LLMError(f"HTTP {r.status_code}")
            body = r.json()
    except LLMError:
        raise
    except Exception as e:  # noqa: BLE001 — never leak a key or a URL into the message
        raise LLMError(f"{type(e).__name__}") from e

    return {
        "bullets": parse_bullets(body),
        "usage": body.get("usage") or {},
        "model": body.get("model") or model,
    }


def parse_bullets(body: dict) -> "list[dict]":
    """Defensive parse. Structured output is REQUESTED, never assumed: providers
    fall back to prose, wrap JSON in fences, or return a bare array."""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError("no message content") from e
    if content is None:
        # Reasoning models spend completion tokens before any content (see CLAUDE.md).
        raise LLMError("null content (token budget exhausted before output?)")
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMError("content was not JSON") from None
        try:
            data = json.loads(text[start:end + 1])
        except ValueError:
            raise LLMError("content was not JSON") from None

    raw = data.get("bullets") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise LLMError("no bullets array")

    bullets = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ids = item.get("obs_ids") or item.get("obs_id") or []
        if isinstance(ids, str):
            ids = [ids]
        bullets.append({
            "beat": str(item.get("beat") or "other").strip().lower(),
            "text": str(item.get("text") or "").strip(),
            "obs_ids": [str(i).strip() for i in ids if str(i).strip()],
        })
    return bullets


# ── the hard gate ──────────────────────────────────────────────────────────────

def validate_citations(bullets: "list[dict]", pack: "list[dict]") -> None:
    """Every bullet cites ≥1 obs_id, and every cited id was in the pack that was SENT.

    "In the pack" — not "in the database". An id that exists but was never shown to
    the model is a fabricated citation that happened to land on a real row, and it is
    rejected exactly like an invented one."""
    allowed = {item["obs_id"] for item in pack}
    if not bullets:
        raise CitationError("the model returned no bullets")
    for i, b in enumerate(bullets):
        if not b.get("text"):
            raise CitationError(f"bullet {i} has no text")
        ids = b.get("obs_ids") or []
        if not ids:
            raise CitationError(f"bullet {i} cites nothing")
        unknown = [o for o in ids if o not in allowed]
        if unknown:
            raise CitationError(
                f"bullet {i} cites {len(unknown)} id(s) absent from the evidence sent: "
                + ", ".join(unknown[:3]))


# ── rendering ──────────────────────────────────────────────────────────────────

def _fmt_window(start_ms: int, end_ms: int, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    s_utc = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    e_utc = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
    return (f"{s_utc:%Y-%m-%d %H:%M} → {e_utc:%Y-%m-%d %H:%M} UTC  \n"
            f"({s_utc.astimezone(tz):%Y-%m-%d %H:%M} → "
            f"{e_utc.astimezone(tz):%Y-%m-%d %H:%M} {tz_name})")


def _beat_order(beats_present: "set[str]") -> "list[str]":
    known = [b for b in BEATS if b in beats_present]
    return known + sorted(beats_present - set(BEATS))


def render(bullets: "list[dict]", rows_by_id: dict, start_ms: int, end_ms: int,
           tz_name: str, failed_sources: "list[str]", deterministic: bool = False,
           reason: str = "") -> str:
    """Markdown. URLs come from the STORE, keyed by obs_id — never from the model."""
    day = datetime.fromtimestamp(end_ms / 1000, timezone.utc).astimezone(
        ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    out = [f"# PYTHIA Monitor — daily brief, {day}", ""]
    out.append("**Coverage window:** " + _fmt_window(start_ms, end_ms, tz_name))
    out.append("")
    if deterministic:
        out.append(f"> **Deterministic brief (no rewrite).** {reason} Bullets below are the "
                   "selected observations verbatim, not summarised.")
        out.append("")
    if failed_sources:
        out.append("> ⚠ **Coverage warning.** These sources failed during this window, so "
                   "anything they would have reported is missing from this brief: "
                   + ", ".join(f"`{s}`" for s in sorted(failed_sources)) + ".")
        out.append("")

    by_beat: dict[str, list] = {}
    for b in bullets:
        by_beat.setdefault(b.get("beat") or "other", []).append(b)

    if not bullets:
        out.append("_No new, changed or removed observations in this window._")
        out.append("")

    for beat in _beat_order(set(by_beat)):
        out.append(f"## {beat.title()}")
        out.append("")
        for b in by_beat[beat]:
            cites = []
            for oid in b.get("obs_ids", []):
                row = rows_by_id.get(oid)
                url = (row or {}).get("url") or ""
                cites.append(f"[{oid[:8]}]({url})" if url else f"`{oid[:8]}`")
            out.append(f"- {b['text']} " + " ".join(cites))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _deterministic_bullets(selected: "list[dict]") -> "list[dict]":
    """Title + citation, honestly unsummarised."""
    label = {"new": "NEW", "changed": "CHANGED", "gone": "GONE"}
    return [{"beat": r.get("beat") or "other",
             "text": f"{label[r['kind']]}: {r.get('title') or '(untitled)'}",
             "obs_ids": [r["obs_id"]]} for r in selected]


# ── budget ─────────────────────────────────────────────────────────────────────

def month_start_ms(at_ms: int) -> int:
    d = datetime.fromtimestamp(at_ms / 1000, timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


# ── the run ────────────────────────────────────────────────────────────────────

async def run_brief(store: "Store | None" = None, at_ms: "int | None" = None,
                    adapter_runs: "list | None" = None, llm=None,
                    notify=None) -> dict:
    """Build, gate, and publish today's brief. Returns a status dict.

    `llm` and `notify` are injectable so the whole path can be exercised offline.
    Returns without publishing on any failure — the previous brief stays latest."""
    store = store or get_store()
    end_ms = at_ms or now_ms()

    previous = store.latest_brief()
    start_ms = previous["coverage_end_ms"] if previous else end_ms - DEFAULT_WINDOW_MS

    tz_name = CONFIG.brief_tz
    brief_date = datetime.fromtimestamp(end_ms / 1000, timezone.utc).astimezone(
        ZoneInfo(tz_name)).strftime("%Y-%m-%d")

    failed_sources = [r.source_id for r in (adapter_runs or []) if r.status == "error"]

    d = delta_mod.compute(store, start_ms, end_ms)
    selected = select(d)
    pack = evidence_pack(selected)
    rows_by_id = store.get_many([item["obs_id"] for item in pack])

    def _publish(bullets, status, model=None, usage=None, cost=None, reason=""):
        markdown = render(bullets, rows_by_id, start_ms, end_ms, tz_name, failed_sources,
                          deterministic=(status == "deterministic"), reason=reason)
        usage = usage or {}
        store.save_brief(brief_date, start_ms, end_ms, markdown, status, model=model,
                         prompt_tokens=usage.get("prompt_tokens"),
                         completion_tokens=usage.get("completion_tokens"),
                         cost_usd=cost, created_ms=end_ms)
        return {"status": status, "brief_date": brief_date, "bullets": len(bullets),
                "coverage_start_ms": start_ms, "coverage_end_ms": end_ms,
                "coverage_warnings": failed_sources, "markdown": markdown,
                "model": model, "cost_usd": cost}

    # Nothing to say. Calling a model to rewrite an empty list would be spending
    # money to produce the sentence below.
    if not pack:
        result = _publish([], "deterministic", reason="Nothing changed in this window.")
        await _deliver(result, notify)
        return result

    # Budget ceiling (plan §10). At the cap the brief still ships, deterministically.
    spent = store.spend_since(month_start_ms(end_ms))
    unknown = store.spend_unknown_rows(month_start_ms(end_ms))
    if spent >= CONFIG.llm_monthly_cap_usd:
        reason = (f"Monthly LLM budget reached (${spent:.4f} of "
                  f"${CONFIG.llm_monthly_cap_usd:.2f} known spend"
                  + (f", plus {unknown} call(s) of unrecorded cost" if unknown else "") + ").")
        log.warning("brief: budget cap reached — deterministic brief, no LLM call")
        result = _publish(_deterministic_bullets(selected), "deterministic", reason=reason)
        await _deliver(result, notify)
        return result

    model = CONFIG.brief_model or CONFIG.llm_model
    call = llm or (lambda p: rewrite_with_llm(p, model, CONFIG.llm_base_url, CONFIG.llm_api_key))

    try:
        answer = await call(pack)
        bullets = answer.get("bullets") or []
        validate_citations(bullets, pack)
    except (LLMError, CitationError) as e:
        # One failure path for both: a fabricated citation and a dead provider are
        # equally reasons not to publish. Yesterday's brief remains the latest.
        log.warning("brief NOT published (%s): %s", type(e).__name__, e)
        store.save_brief(brief_date, start_ms, end_ms, "", "failed",
                         model=model, created_ms=end_ms)
        return {"status": "failed", "brief_date": brief_date,
                "reason": f"{type(e).__name__}: {e}",
                "latest_unchanged": bool(previous),
                "coverage_start_ms": start_ms, "coverage_end_ms": end_ms}
    except Exception as e:  # noqa: BLE001 — an unexpected fault must not publish either
        log.warning("brief NOT published (unexpected %s)", type(e).__name__)
        store.save_brief(brief_date, start_ms, end_ms, "", "failed",
                         model=model, created_ms=end_ms)
        return {"status": "failed", "brief_date": brief_date,
                "reason": type(e).__name__, "latest_unchanged": bool(previous)}

    usage = answer.get("usage") or {}
    # Cost comes from the provider's usage field or it is NULL. An estimate reads
    # exactly as authoritative as a measured figure, so none is made.
    cost = usage.get("cost")
    cost = float(cost) if isinstance(cost, (int, float)) else None
    used_model = answer.get("model") or model
    store.record_spend("brief", used_model, cost, ts_ms=end_ms)

    result = _publish(bullets, "published", model=used_model, usage=usage, cost=cost)
    await _deliver(result, notify)
    return result


async def _deliver(result: dict, notify=None) -> None:
    """Push the brief. A delivery failure never unpublishes it."""
    from .ntfy import send_brief
    fn = notify or send_brief
    try:
        result["delivery"] = await fn(result)
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy delivery failed: %s", type(e).__name__)
        result["delivery"] = {"sent": False, "error": type(e).__name__}
