# bitfactory — Decisions

A running log of resolved [open-questions.md](open-questions.md) items. Each
entry is a v1 default, not a permanent constraint — "revisit when" notes
where a decision is expected to be reopened.

## Orchestration

- **Single orchestrator/planner loop at a time.** Matches the atomic-rename
  claim in `backlog/` acting as the lock (architecture.md). Multiple
  concurrent planners would need real locking beyond that; not needed now.
- **Orchestrator trigger mechanism: still open.** See
  [open-questions.md](open-questions.md) — this is the one decision
  deliberately left for later, staged as: Phase 0 fully interactive → Phase 1
  headless but manually triggered or scripted → final trigger design decided
  once the pipeline moves off the pure filesystem ticket store (Phase 4).

## Concurrency

- **Max 3 tickets in `in_progress/` at once (v1).**
- **Max 3 worker agents running in parallel per ticket (v1).**
- **No separate token/cost budget per ticket for v1** — the retry cap (below)
  is the only cost bound for now. *Revisit when:* Phase 0 shows what a real
  ticket actually costs, or a ticket burns unexpectedly high cost without
  hitting the retry cap.

## Definition of done / human gate

- **Approval gate is priority-based: high-priority tickets require human
  approval before `in_testing/ → done/`; low and medium go dark
  automatically** once tests pass and acceptance criteria are judged met.
- **Approval mechanism: PR/MR review on a git forge.** The ticket's feature
  branch is pushed and opened as a PR; approval = PR approved/merged.
  **Remote used for this: the local Gitea instance** (self-hosted on the
  Unraid server), not the `origin` GitHub remote — Phase 0/1 test runs
  target Gitea so an unattended run can't do anything visible on the real
  GitHub repo while the pipeline is still unproven. GitHub is the eventual
  production target once the pipeline has a track record; switching is a
  remote/config change, not a design change, since Gitea speaks a
  compatible PR flow. **Consequence either way:** a git-forge remote is
  needed as soon as any high-priority ticket reaches `in_testing/`, even
  though full GitHub Issues/Projects *intake* integration is still deferred
  to Phase 4 (see [overview.md](overview.md#non-goals-v1)).
- **No earlier gate for v1** — only the end gate above; the planner's
  subtask breakdown is not reviewed before workers start. *Revisit when:* bad
  subtask decompositions turn out to be a recurring problem.

## Git and merging

- **Subtasks that unavoidably touch the same file still run in parallel;
  conflicts are resolved at merge time**, not by serializing them upfront.
  This happens during the planner's serialized-merge step (architecture.md),
  which also answers who owns conflict resolution: the **planner**, during
  integration — the tester never sees an unresolved conflict, only the
  already-integrated feature branch.

## Failure handling

- **Retry cap: 3.** A ticket lineage (original + its `bug_` descendants) can
  fail validation 3 times before the tester escalates to a human (a
  `needs_human/` directory) instead of filing another `bug_` ticket.
- **Crash recovery: resume automatically.** If the orchestrator is
  interrupted with a ticket mid-flight in `in_progress/`, the planner
  re-derives what's left to do from the ticket's `subtasks[]` state and git
  history on restart, rather than requiring human triage by default.

## Isolation and safety

- **Isolation depth for v1: git worktree per worker only** — no
  devcontainers yet. *Revisit when:* a worker's need for a different
  runtime/dependency environment than the host, or a desire for stronger
  sandboxing, makes worktree-only isolation insufficient.
- **Guardrails for unattended workers: tight by default.** Allowlisted Bash
  commands, no unrestricted network access, writes scoped to the worker's
  own worktree. Loosened deliberately per-role only if a specific worker
  genuinely needs more, not as a blanket default.

## Observability

- **Log lines only for v1** — the `## Log` section appended to each ticket
  file (architecture.md) is the only persisted audit trail; no separate
  per-ticket full-transcript storage. *Revisit when:* a log-line summary
  turns out to be insufficient to debug a bad unattended run.

## Agent roster

- **planner and tester are bitfactory-specific agents** (not yet written)
  that delegate implementation work to generic installed role agents rather
  than doing it themselves.
- **v1 worker roster confirmed as proposed** in
  [../agents/README.md](../agents/README.md) — backend-developer,
  frontend-developer, fullstack-developer, language-specific `*-pro` agents,
  test-automator, code-reviewer, database-optimizer/sql-pro,
  git-workflow-manager. Expand deliberately as real tickets show a need for
  an uncovered role, not preemptively.
