# Contributing to PYTHIA

> **2026-08-29 — this document describes the pre-pivot build.** PYTHIA is now a
> world-**monitoring** service; forecasting is retired (`PYTHIA_MODE=research` archives it).
> The launchers this file mentions — `run-all.sh`, `PYTHIA.command`, `PYTHIA.app`,
> `daily-digest.py` — and the Osiris overlay in `integrations/osiris/` were moved to
> `.trash/2026-08-29/` and no longer exist at these paths. The plan of record is
> `PYTHIA-MONITOR-V1-PLAN.md`; run the engine with `uv run python -m engine.run`.

Thanks for wanting to help. PYTHIA is a **local, keyless world-watching prediction oracle**, and contributions that keep it that way — fast, private, and free — are very welcome.

`main` is protected: all changes land through a **pull request** that gets reviewed and approved. Push directly to your fork, then open a PR here.

## Ground rules (the PYTHIA ethos)

Please keep these in mind — a PR that breaks them will be asked to change:

1. **Keyless and free.** Every data source must work with **no API key, no account, and no cost.** If a feed needs a key or a paid tier, it doesn't belong in core. (We turned down ACLED for exactly this reason; UNHCR, WHO, World Bank, OONI, GDELT, DeepStateMap, etc. are the kind of sources we use.)
2. **Local-first.** No cloud services, no telemetry, no phoning home. It runs on the user's hardware.
3. **No secrets, ever.** Never commit `.env`, keys, tokens, or personal data. `.env`, `*.pem`, and `runs/*.jsonl` are gitignored — keep it that way.
4. **Small, focused PRs.** One feature or fix per PR is much easier to review and merge.

## How the repo is laid out

| Path | What it is |
|---|---|
| `engine/` | The PYTHIA oracle — Python + FastAPI. Pulls & fuses feeds (`osiris_intake`, `world_state`), runs the forecast + chat (`oracle`), the persona swarm (`swarm`), and the API (`server`). **This is the code that lives here.** |
| `integrations/osiris/` | An **overlay** applied on top of a separate [Osiris](https://github.com/simplifaisoul/osiris) checkout — the predictions deck, chat, map layers, and API routes. Osiris itself is **not** redistributed; see `integrations/osiris/INSTALL.md`. |
| `run-all.sh` · `PYTHIA.app` | One-tap launchers. |

## Dev setup

**Prerequisites**
- [Ollama](https://ollama.com) running with a chat model pulled (`ollama pull llama3.1`).
- A [Osiris](https://github.com/simplifaisoul/osiris) checkout with the overlay applied — see [`integrations/osiris/INSTALL.md`](integrations/osiris/INSTALL.md).
- Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<your-username>/Pythia && cd Pythia
cp .env.example .env
./run-all.sh          # Osiris on :3000, engine on :8088
```

## Before you open a PR

- **Engine changes:** confirm it imports and runs —
  ```bash
  uv run python -c "import engine.server"
  ```
- **UI / overlay changes:** typecheck in your Osiris checkout —
  ```bash
  npx tsc --noEmit
  ```
- Match the surrounding code (typed Python, TypeScript strict, the existing style).
- If it's visual, drop a screenshot in the PR.

## Adding a new layer / data source

Most-wanted contributions are new **keyless** feeds. The pattern:
1. Add an Osiris route under `integrations/osiris/routes/` that fetches the source and returns clean GeoJSON/JSON.
2. Wire it into the map (source + layer + toggle) and note the edit in `INSTALL.md`.
3. Feed it to the oracle in `engine/osiris_intake.py` (add to `FEEDS` + a small summarizer) so predictions can use it.

Country-level layers can reuse `integrations/osiris/lib/countryCentroids.ts` (ISO3 / ISO2 / name → coordinates, no geocoding key needed).

## Reporting bugs & ideas

Open an [issue](https://github.com/jangles-byte/Pythia/issues) — for bugs, include what you did, what happened, and the relevant logs. Feature ideas and new keyless sources are very welcome too.

## License

By contributing, you agree your work is licensed under the project's [MIT License](LICENSE).
