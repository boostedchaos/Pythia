#!/usr/bin/env bash
# PYTHIA oracle — one machine:  Osiris UI (:3000)  +  PYTHIA engine (:8088)
# The oracle uses your local LLM (Ollama, :11434) as its brain. Ctrl-C stops all.
set -euo pipefail

PYTHIA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OSIRIS_DIR="${OSIRIS_DIR:-$HOME/osiris}"

# Tailscale URL (for your phone), if available.
TS_BIN="$(command -v tailscale || true)"
[ -z "$TS_BIN" ] && [ -x "/Applications/Tailscale.app/Contents/MacOS/Tailscale" ] && TS_BIN="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
TS_IP=""; [ -n "$TS_BIN" ] && TS_IP="$("$TS_BIN" ip -4 2>/dev/null | head -n1 || true)"

pids=()
cleanup() { echo; echo "[pythia] shutting down..."; for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup INT TERM EXIT

# clear stale servers so relaunches are clean
echo "[pythia] clearing stale servers on :3000 :8088 ..."
for p in 3000 8088; do lsof -ti tcp:$p -sTCP:LISTEN 2>/dev/null | xargs -r kill -9 2>/dev/null || true; done
pkill -9 -f "engine.run" 2>/dev/null || true
sleep 1

# the oracle needs a local LLM (Ollama). Warn if it's not up.
if ! curl -s -o /dev/null --max-time 3 http://localhost:11434/v1/models; then
  echo "[pythia] ⚠  Ollama not reachable on :11434 — start it (open the Ollama app, or run 'ollama serve')."
fi

echo "[pythia] PYTHIA engine  -> http://localhost:8088"
( cd "$PYTHIA_DIR" && PYTHIA_DEV_ORIGINS="$TS_IP" uv run python -m engine.run ) & pids+=($!)

echo "[pythia] Osiris/PYTHIA UI -> binding 0.0.0.0:3000"
( cd "$OSIRIS_DIR" && PYTHIA_ENGINE_URL="http://localhost:8088" PYTHIA_DEV_ORIGINS="$TS_IP" \
    npm run dev -- -H 0.0.0.0 -p 3000 ) & pids+=($!)

# open the dashboard once it's serving
( for _ in $(seq 1 90); do curl -s -o /dev/null "http://localhost:3000" && { open "http://localhost:3000"; break; }; sleep 2; done ) &

echo
echo "════════════════════════════════════════════════════════"
echo "  PYTHIA oracle — open the dashboard:"
echo "    • this Mac : http://localhost:3000"
[ -n "$TS_IP" ] && echo "    • phone    : http://$TS_IP:3000  (Tailscale)"
echo "════════════════════════════════════════════════════════"
wait
