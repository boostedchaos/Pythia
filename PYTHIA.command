#!/bin/bash
# ╔══════════════════════════════════════════════════════════════╗
# ║  PYTHIA — double-click to launch the prediction oracle        ║
# ║  Starts Osiris (:3000) + PYTHIA engine (:8088); local LLM     ║
# ║  (Ollama) is the brain. Opens the dashboard. Ctrl-C to stop.  ║
# ╚══════════════════════════════════════════════════════════════╝
cd "$(dirname "$0")" || exit 1

# Finder-launched shells have a bare PATH — make sure uv / npm / node are found.
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
[ -f "$HOME/.zprofile" ] && source "$HOME/.zprofile" 2>/dev/null
[ -f "$HOME/.zshrc" ] && source "$HOME/.zshrc" 2>/dev/null

# run-all.sh handles starting services AND opening the dashboard (single open).
exec ./run-all.sh
