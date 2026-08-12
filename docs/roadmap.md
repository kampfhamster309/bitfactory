# bitfactory — Roadmap

Phased so each stage is independently useful and de-risks the next one,
rather than building the full unattended pipeline before any of it has been
exercised end to end.

## Phase 0 — Manual single-ticket walkthrough

Run the whole lifecycle (backlog → planner → workers → tester → done) for
one hand-written ticket, driven interactively from this Claude Code session
acting as the orchestrator. No automation loop, no locking, no concurrency
caps — the goal is to validate the ticket format, the planner/tester agent
definitions, and the git branching model actually work before automating
anything around them. If the walkthrough exercises a high-priority ticket's
approval gate, push to the local Gitea instance for that, not `origin`.

**Exit criteria:** one ticket goes end to end to `done/` with a clean,
inspectable git history and a ticket file that accurately reflects what
happened. **Met** — twice over, in fact (once with a human standing in
for the subagents, once for real).

## Phase 1 — Headless, still single-threaded

Replace "a human re-triggers each step interactively" with headless
invocations of Claude Code (`claude -p`) for the planner/tester steps. The
exact trigger — manually run by hand, or a simple polling script — is
deliberately not fixed yet (see
[open-questions.md](open-questions.md#orchestrator-trigger-mechanism)); pick
whichever is convenient at the time. The real trigger-mechanism design is
deferred to Phase 4, once there's an actual external ticket source to
design it around. Still one ticket in flight at a time — this phase is
about proving headless invocation works, not about parallelism yet.

Every invocation (`claude -p` included) must run with its working
directory set to the target repo root — `planner`/`tester` are project-level
agents and aren't discovered otherwise (see
[decisions.md](decisions.md#orchestration)).

Before the first headless run: the target repo needs a `.claude/settings.json`
(copied and adjusted from [settings.json.example](settings.json.example),
see [architecture.md](architecture.md#permission-configuration)) and every
headless invocation needs `--permission-mode dontAsk` passed explicitly —
otherwise it'll stall or silently deny on the first action outside the
default permission set, with nobody watching to approve it. **The target
repo's path also needs `hasTrustDialogAccepted: true` in `~/.claude.json`**
— found this the hard way on the first attempt: without it, every
`permissions.allow` rule in `settings.json` gets silently ignored
regardless of how it's configured (see
[decisions.md](decisions.md#orchestration)). **A real git credential
helper needs to be configured too** — not the `-c http.extraHeader=...`
flag used manually so far, which breaks the `Bash(git push origin *)`
permission match under `dontAsk`; see
[architecture.md](architecture.md#secrets) for the fix. Found this one
because the tester correctly refused to force a workaround and logged
the blocker instead of guessing — worth treating as the intended
behavior, not a bug, even though it meant a stalled run.

Note: if a high-priority ticket goes through this phase, its approval gate
requires a PR review ([decisions.md](decisions.md#definition-of-done--human-gate)).
Test runs in this phase target the local Gitea instance, not the `origin`
GitHub remote — keeps unattended runs from doing anything visible on the
real repo while the pipeline is still unproven, ahead of the GitHub
*intake* integration planned for Phase 4.

**Exit criteria:** a ticket dropped into `backlog/` reaches `done/` (or
`needs_human/`) via a headless Claude Code invocation, without a human
driving each step interactively. **Met** — the first attempt found and
needed fixes for three real bugs (workspace trust, git push
authentication, dead `Write(...)` permission rules) along the way; the
next headless run afterward completed fully unattended, including the
push.

## Phase 2 — True worker parallelism

Worktree-per-worker isolation already exists — it's been part of the
design since before Phase 0 and every ticket so far has used it, just
never for more than one worker at a time, since every ticket to date has
had exactly one subtask. What Phase 2 actually still needs is a ticket
the planner decomposes into 2+ genuinely independent subtasks, dispatched
concurrently rather than one after another, so the planner's serialized
merges — currently only theoretical, since there's never been a second
merge to serialize against — get exercised for real, including whatever
happens when two subtasks land close together or (deliberately, as a
follow-up) actually touch the same file.

Devcontainers are *not* planned for this phase — nothing so far suggests
worktree-only isolation is insufficient (three tickets have run fine
without it), and [decisions.md](decisions.md#isolation-and-safety) already
says to revisit only if a worker genuinely needs a different runtime than
the host or stronger sandboxing than a worktree provides. Skip until
something actually demands it.

**Exit criteria:** a ticket with 2+ independent subtasks completes with
workers running concurrently, isolated from each other, with clean serial
merges.

## Phase 3 — Multiple tickets in flight, priority-aware

Add the concurrency caps and locking discussed in
[open-questions.md](open-questions.md#concurrency-and-cost), and make the
orchestrator actually respect ticket priority when choosing what to work on
next rather than pure FIFO.

**Exit criteria:** multiple tickets progress through the pipeline
concurrently without collisions, and a `high`-priority ticket added after a
`low`-priority one gets picked up first.

## Phase 4 — External ticket sources

Add an intake adapter for GitHub Issues/Projects (or Jira) that creates
tickets in the same file format, so `backlog/` isn't the only entry point.
Bug tickets filed by the tester keep working exactly as before. This is
also where the orchestrator trigger mechanism finally gets decided for
real (see [open-questions.md](open-questions.md#orchestrator-trigger-mechanism))
— e.g. a webhook from the ticket source is a natural trigger once one
exists, which wasn't true in Phases 0–3.

**Exit criteria:** an issue created externally shows up as a ticket in
`backlog/` and flows through the pipeline identically to a hand-written one.

## Phase 5 — CI/CD to production

Replace (or extend) "moved to `done/`" with an actual deploy pipeline
trigger, once enough tickets have gone through Phase 0–4 to trust the
pipeline's output without a human in the loop by default.

**Exit criteria:** intentionally left open — this phase depends on what
"production" means for whatever the factory ends up building.
