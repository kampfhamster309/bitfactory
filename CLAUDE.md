# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

bitfactory is an experiment in an agent-based "dark factory" for software:
user stories flow into `backlog/` as tickets, and a pipeline of Claude Code
agents (planner → workers → tester) plans, implements, tests, and merges
them with as little human involvement as possible.

**Current status: Phase 0 validated.** The planner/tester agents
(`.claude/agents/`, also symlinked into `agents/` for visibility) and the
ticket-filing helper (`scripts/ticket.py`) have driven two tickets end to
end against a sandbox target repo — one plain, one through the PR-gated
path — fully interactively, no orchestrator loop yet. See `docs/roadmap.md`
for what's next (Phase 1: headless invocation); don't assume tooling exists
beyond what's referenced below.

## Read this first, in order

1. `docs/overview.md` — vision, goals, and a sanity check of the original
   workflow draft. Read this first; it explains *why* the design looks the
   way it does.
2. `docs/architecture.md` — the actual v1 design: ticket format, git
   branching model, concurrency/locking, validation protocol, guardrails,
   secrets handling. This is the spec to implement against.
3. `docs/decisions.md` — resolved design decisions with rationale (the
   concrete numbers/policies architecture.md relies on).
4. `docs/open-questions.md` — the one thing still genuinely undecided (the
   orchestrator trigger mechanism). Check here before assuming something is
   settled that isn't.
5. `docs/roadmap.md` — phased build-out (Phase 0 through 5). Phase 0
   (manual single-ticket walkthrough, writing the planner/tester agent
   definitions) is the current/next phase — nothing later has started.
6. `docs/glossary.md` — term definitions if something is unclear.
7. `agents/README.md` — which agents play which role; the v1 worker roster
   (mapped to installed `voltagent-*` plugin agents).
8. `docs/ticket-template.md` — the schema `scripts/ticket.py` implements;
   read this if you need to know a field's meaning, not to file tickets by
   hand (use the script instead).

## Commands

- `scripts/ticket.py new [flags | interactive]` — file a new ticket into
  `backlog/`: generates the collision-safe ULID id, fills out frontmatter,
  self-validates before writing. `--bug-of <ticket-id>` for bug tickets
  (auto-computes `retry_count`). Run with `--help` for all flags; omit
  flags to be prompted interactively.
- `scripts/ticket.py validate <path>` — check an existing ticket file
  against the same rules; non-zero exit on failure. Stdlib-only (no venv/
  install step) — this is the only tooling in the repo so far.

## Invariants that must not be violated when implementing this

These are load-bearing design decisions from `architecture.md`/`decisions.md`
— violating them silently reintroduces the concurrency/safety bugs the
design was built to avoid, so don't "simplify" past them without updating
those docs first:

- **A ticket's directory is its status**, not its frontmatter. The
  `status:` field in a ticket file is a convenience mirror for grepping —
  never treat it as authoritative if it disagrees with which of
  `backlog/`/`in_progress/`/`in_testing/`/`done/`/`needs_human/` the file is
  actually in.
- **Ticket IDs are `<ULID-or-timestamp>-<slug>.md`**, bug tickets add a
  `bug_` prefix to the slug. Never go back to sequential numbering — it was
  explicitly rejected for collision reasons. File tickets with
  `scripts/ticket.py new`, not by hand — it's what actually generates a
  correct id and validates the result.
- **Claiming a ticket is an atomic `rename(2)` out of `backlog/`** — this is
  the lock. It only works because exactly one orchestrator/planner loop
  runs at a time (v1 assumption); don't add a second concurrent planner
  loop without redesigning locking first.
- **One git worktree per worker, never a shared checkout.** A subtask
  branch name alone isn't isolation — two agents editing the same working
  directory will clobber each other's uncommitted changes regardless of
  which branch they intend to commit to.
- **Subtask branches are `subtask/<ticket-id>/<n>`, never nested under
  `feature/<ticket-id>`.** Git refs are hierarchical, so a ref can't be
  both a leaf and a directory prefix for another ref —
  `feature/<ticket-id>/subtask-<n>` cannot coexist with `feature/<ticket-id>`
  and will fail outright. Found the hard way during Phase 0.
- **The planner merges subtask branches serially**, one at a time, and owns
  conflict resolution during that step. The tester never sees an unresolved
  conflict — only the already-integrated feature branch.
- **Concurrency caps: max 3 tickets in `in_progress/`, max 3 workers per
  ticket** (v1 defaults, configurable, not to be silently exceeded).
- **Retry cap: 3.** A ticket lineage (original + its `bug_` descendants)
  gets 3 validation failures before the tester escalates to `needs_human/`
  instead of filing another `bug_` ticket.
- **Approval gate has two independent triggers:** `priority: high`, or a
  ticket with `needs_manual_verification: true` (any acceptance criterion
  tagged `(manual)` — something no agent can check mechanically, e.g. a GUI
  actually rendering correctly). Either one routes through PR review
  instead of straight to `done/`; don't conflate the two by forcing
  priority up just to get a manual-verification ticket reviewed. Approval
  currently targets the **local Gitea instance**, not the `origin` GitHub
  remote — don't point PR-approval flows at `origin` until the pipeline has
  earned that (see `decisions.md`).
- **The planner holds new tickets that look likely to conflict with an open
  PR.** Before claiming a ticket, it checks `in_testing/` tickets with
  `pr_url` set (gated, awaiting human review — an unbounded wait, unlike
  ordinary in-flight tickets) and compares their exact touched-files list
  against the new ticket's story. Likely overlap → leave it in `backlog/`
  and log why, rather than claim it (see `architecture.md`'s
  "Cross-ticket conflict avoidance").
- **Workers run under tight guardrails by default:** allowlisted Bash, no
  unrestricted network, writes scoped to their own worktree. Only the
  planner and tester ever need the git-forge token, and it must never be
  committed, logged, or written into a ticket's `## Log` section.
