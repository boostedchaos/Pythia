# PYTHIA Monitor — autonomous build prompt

**How to use this file.** Open a fresh Claude Code session in
`~/Documents/PROJECTS/Pythia/Pythia`. Set the active model to **Claude Fable 5**. Set
`/effort medium`. Then paste everything between the `=== PROMPT ===` markers below as your first
message.

Do not paste the setup notes — only the prompt block.

---

## Setup notes (read these, don't paste them)

- **Model:** Fable 5, effort `medium`. Raise to `high` only if it visibly under-plans. Never
  `xhigh` or `max` — on Fable those cost more and produce worse, over-large changes.
- **Pattern:** architect + delegate. Fable plans and delegates; Opus 5 subagents do the work.
  Fable should be roughly 5–15% of the tokens.
- **Runtime:** expect several hours across Phase 0.5 and Phase 1. It commits at phase boundaries,
  so an interruption is recoverable.
- **What it will touch:** this repo, and the VM at `192.168.0.28` only. It is told not to push and
  not to touch any other homelab host.
- **Checking on it:** `/workflows` shows live agent progress. `git log --oneline monitor-v1` shows
  phase commits.
- **If it stops early:** paste `Continue. Re-read PYTHIA-MONITOR-V1-PLAN.md §7 and resume at the
  first phase whose acceptance criteria are not met.`

---

=== PROMPT ===

You are the architect for a build I cannot supervise. Plan the work, delegate execution to Opus 5
subagents, and gate each phase on evidence.

## Context

I'm building PYTHIA Monitor: a private, always-on world-monitoring service for one user (me). It
watches five beats — AI, cybersecurity, global politics, US healthcare regulation, and markets —
tracks what *changed*, and writes me a cited daily brief. It replaces a forecasting experiment that
was measured and failed. The output enables me to stay current in my fields without reading
feeds all day, and to let other agents query the same evidence.

I have a traumatic brain injury that impairs multi-step number work. I cannot easily catch a wrong
figure in a deliverable. Every number you or your agents put in a report must name the file or
command output it came from. If a number isn't in a source, mark it TODO and say so — never fill a
gap with an estimate.

## Read first, in this order

1. `PYTHIA-MONITOR-V1-PLAN.md` — the plan of record. §2 decisions, §3 what already shipped,
   §5 audit findings, §6 how success is measured, §7 the roadmap, §8 feed acquisition.
2. `STATE.md` — the forecasting experiment's record.
3. `CLAUDE.md` — project conventions.
4. `git log --oneline -5` and `git show --stat 5fcd8f3` — Phase 0 is already done and committed.

Do not re-plan Phase 0. It is complete and verified. Start at Phase 0.5.

## Scope

Build **Phase 0.5**, then **Phase 1**, exactly as specified in §7 of the plan. Stop after Phase 1
and write a report. Do not start Phase 2.

Phase 0.5 is the priority: a daily brief that says what is NEW, CHANGED and GONE since yesterday,
with a source link on every line, covering all five beats. Phase 1 is the durable event spine
underneath it.

## Decisions already made — do not relitigate

These are in §2 of the plan. They are settled:

- Feeds are fetched **directly**. Osiris is dropped. Delete `integrations/osiris/` once direct
  feeds land.
- Delivery is **ntfy**. Remote access is **Tailscale** plus a bearer token.
- Retention is **1 year** then prune.
- Alerts observe **quiet hours 22:00–07:00** with a small urgent-override set.
- LLM spend ceiling is **under $5/month**, enforced in code. Clustering and change detection are
  **deterministic — no LLM in the change-detection path**.
- Markets ships **broad macro defaults only**, never personal holdings.
- Brief time **07:00 America/Chicago**. Healthcare scope **US only**.

## Boundaries

- **Never `git push`.** Commit at phase boundaries on branch `monitor-v1` only.
- **Never touch another homelab host.** Only this repo and the VM at `192.168.0.28`.
- Never `git stash` in `osiris-live/`.
- Do not modify `review-fixes` — it is the research archive.
- Secrets live only in `~/pythia/deploy/compose/.env` on the VM. Never in the repo, never in an
  image, never in a log line.
- For any destructive operation, move to a `.trash/` directory rather than deleting.

## The target host

Debian 13 VM, `pythia@192.168.0.28`, key `~/.ssh/id_ed25519_pythia`, passwordless sudo.
Docker 29.7.2 and Docker Compose v5.5.0 are installed. Repo at `~/pythia`, stack in
`~/pythia/deploy/compose`. Deploy and health commands are in §13 of the plan.

## How I want the work verified

This project has already been bitten by checks that looked clean and proved nothing. These rules
are not optional, and they apply to your agents as much as to you.

- **A check only finds what it was told to look for.** Report "clean against N specific patterns",
  never "it's clean".
- **Prove every checker fires.** Before trusting a passing test, revert the fix it guards and
  confirm the test fails. A test broken by a bad path and a genuinely passing test look identical.
- **Verify against the real producer, never a synthetic stand-in.** Phase 0 proved its healthy path
  with a fake feed server. Phase 0.5 must exercise real sources and read what the *receiver* got.
- **A vendor health endpoint proves reachability, not capability.** Force one real, representative
  call and quote what it returned.
- **Read state back after writing it.** A write's own success response is not confirmation.
- **Verify the deployed artifact, not the source.** Tests run where every path exists by
  definition. Check what the running container actually serves.
- **Never pipe a command whose success matters** — a pipeline returns the last command's status.
  Capture it and echo the exit code.
- **When a third-party tool misbehaves, search its issue tracker before forming any hypothesis.**
- **Never state an untested cause.** "This is most likely, and here is the check that confirms it"
  costs the same words as a confident wrong answer.
- **When you add work a checker covers, confirm its checked-count went up.** A silent skip looks
  exactly like a pass.
- **A defect has copies.** Grep for the pattern, not the file you were editing.

## Acceptance gates

Do not advance a phase until its §7 acceptance criteria are met **and evidenced by tool output you
can point at**. In particular:

- Phase 0.5 does not pass until a **planted fabricated citation is rejected** by the validator, and
  you show the rejection.
- Phase 0.5 does not pass until a **planted duplicate observation produces one bullet, not two**.
- Phase 0.5 does not pass until a **failed provider call is shown leaving yesterday's brief
  intact**.
- Phase 1 does not pass until an **identical source record keeps its identity across a container
  restart**, shown by reading the row back.
- Phase 1 does not pass until a **market instrument produces one story with price history**, not N
  events (see plan §5.11).

For each gate, run it against a known-bad input first to prove the gate fires.

## Orchestration

Delegate independent subtasks to Opus 5 subagents at effort `high` and keep working while they run.
Prefer async over blocking. Intervene only when a subagent goes off track or lacks context.

Use effort `xhigh` for exactly one seat: a fresh adversarial verifier that gates each phase commit,
briefed only on the phase's acceptance criteria and given no knowledge of how the work was done.
Sonnet 5 at `medium` is fine for wide mechanical lanes — checking many candidate feed URLs for
reachability and terms, converting fixtures — but never for a verdict, a verification stage, or a
security-sensitive slice.

Don't predefine subagent roles beyond that verifier; pick the right ones per task. Don't spawn a
subagent for work that takes a handful of tool calls. Keep spawn counts low.

Every phase boundary: have a fresh subagent verify the work against the plan's acceptance criteria
before you commit.

## Working style

When you have enough information to act, act. Don't re-derive established facts, re-litigate a
settled decision, or narrate options you won't pursue. If you're weighing a choice, give a
recommendation, not a survey.

Don't add features, refactor, or introduce abstractions beyond what the task requires. Do the
simplest thing that works. Only validate at system boundaries.

Deliver what was asked at the scope intended. Make routine judgment calls yourself and note them;
don't quietly widen, narrow, or transform the task. Finish the whole task — report completion only
when it's fully done. If something genuinely can't be finished, do the rest and state plainly
what's missing and why.

Before reporting progress, audit each claim against a tool result from this session. Only report
work you can point to evidence for; if it's unverified, say so. If tests fail, say so with the
output.

You're operating autonomously; I can't answer mid-task, so don't ask "Want me to…?". For reversible
actions that follow from this request, proceed. Before ending your turn, if your last paragraph is
a plan, a question, or a promise ("I'll…"), do that work now. End only when done, or blocked on
something only I can provide.

## Feed acquisition — a specific warning

Plan §8 lists candidate sources. **They are candidates, not verified facts.** Some of what a
document or a model remembers about an API being free, keyless, or stable is wrong. For every feed
you adopt: make one real call, confirm it is reachable, confirm whether a key is needed, check the
terms permit this use, record a fixture of the actual response, and write down what you verified.
Never adopt a source because this plan named it.

## When you're done

Update `PYTHIA-MONITOR-V1-PLAN.md` — mark the phases done, record what each acceptance gate showed,
and add any new findings in the §5 style. Update `STATE.md` with dated entries. Add durable
cross-session lessons to `~/.claude/memory/domain/pythia.md` — one lesson per entry, with the cost
of getting it wrong.

Then write me a short report in plain language: what works, what you verified and how, what you
could not verify, what's left. Lead with the bottom line. Keep paths and commands exact.

=== PROMPT ===
