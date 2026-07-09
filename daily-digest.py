"""PYTHIA daily world digest — the repurposed deliverable (2026-07-08).

Pulls the LLM-free fused world view from the engine (GET /agent/view), makes ONE
cheap LLM call to write a compact daily digest, and saves it to ../digests/YYYY-MM-DD.md
(+ ../digests/latest.md) — next to the checkout, outside the repo. Runs via the
"PYTHIA Daily Digest" scheduled task (normal privileges, no admin). Cost: ~1 cent/day.
Stdlib only.

Run manually (from the repo): uv run python daily-digest.py
"""
from __future__ import annotations

import datetime
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # repo root
ENGINE = "http://localhost:8088"
# ponytail: digests write NEXT TO the checkout (winbox: pythia-win11\digests) so generated
# output never dirties git status; relocate by editing this one constant
DIGEST_DIR = ROOT.parent / "digests"
MAX_EVENTS_PER_DOMAIN = 8
FALLBACK_MODEL = "deepseek/deepseek-v4-pro"


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.split(" #")[0].strip()
    return out


def get_credentials() -> tuple[str, str]:
    env = read_env(ROOT / ".env")
    key = env.get("LLM_API_KEY") or env.get("OPENROUTER_API_KEY")
    if not key:  # Mac-pattern fallback, harmless if absent on this box
        key = read_env(Path.home() / ".hermes" / ".env").get("OPENROUTER_API_KEY")
    if not key:
        sys.exit("no OpenRouter key found in Pythia/.env or ~/.hermes/.env")
    return key, env.get("LLM_MODEL") or FALLBACK_MODEL


def fetch_world() -> dict:
    with urllib.request.urlopen(f"{ENGINE}/agent/view", timeout=30) as r:
        return json.load(r)


def build_prompt(view: dict, today: str) -> str:
    lines = []
    for domain, events in sorted(view.get("events_by_domain", {}).items()):
        top = sorted(events, key=lambda e: -(e.get("salience") or 0))[:MAX_EVENTS_PER_DOMAIN]
        lines.append(f"## {domain}")
        for e in top:
            lines.append(f"- {e.get('title', '')}: {str(e.get('summary', ''))[:200]}")
    events_text = "\n".join(lines)
    return (
        f"You are writing a daily world-situation digest for {today} from live feed data below.\n"
        "Write compact markdown: a 3-sentence TOP LINE, then one short section per domain that has "
        "something genuinely notable (skip quiet domains), 2-4 bullets each, concrete facts only — "
        "no predictions, no probabilities, no filler. End with a one-line 'Watch today' item. "
        "Keep the whole digest under 400 words.\n\n"
        f"LIVE EVENTS ({view.get('event_count', 0)} total):\n{events_text}"
    )


def call_llm(key: str, model: str, prompt: str) -> str:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            # reasoning models spend completion tokens on hidden thinking first — keep this generous
            "max_tokens": 4000,
        }).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    return (data["choices"][0]["message"].get("content") or "").strip()


def main() -> None:
    today = datetime.date.today().isoformat()
    key, model = get_credentials()
    view = fetch_world()
    if not view.get("event_count"):
        sys.exit("engine returned 0 events — is the Osiris UI on :3001 up?")
    digest = call_llm(key, model, build_prompt(view, today))
    if not digest:
        sys.exit("LLM returned empty content")
    DIGEST_DIR.mkdir(exist_ok=True)
    digest = digest.strip()
    if digest.startswith("# "):  # LLM emits its own H1 — drop it, ours is the title
        digest = digest.split("\n", 1)[1].strip() if "\n" in digest else ""
    body = f"# World digest — {today}\n\n{digest}\n\n---\n*{view.get('event_count')} live events · model {model} · PYTHIA monitor mode*\n"
    (DIGEST_DIR / f"{today}.md").write_text(body, encoding="utf-8")
    (DIGEST_DIR / "latest.md").write_text(body, encoding="utf-8")
    print(f"digest written: digests/{today}.md ({len(digest)} chars, {view.get('event_count')} events)")


if __name__ == "__main__":
    main()
