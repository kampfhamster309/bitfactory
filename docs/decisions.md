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
- **Project-level agents (planner/tester) are only discovered when the
  session/invocation is rooted at the target repo itself, not a parent
  directory holding multiple projects.** Looked like a subagent-registration
  bug during Phase 0's first walkthrough (`.claude/agents/planner.md`
  wasn't showing up as an invokable agent type, even after a session
  restart) — verified it was actually this: the session doing the
  dispatching was rooted in bitfactory's own parent directory (developing
  bitfactory and running it against the sandbox target side by side), not
  in the target repo. A session rooted directly in the target repo picks
  `planner`/`tester` up correctly. Not a design flaw, just an invocation
  requirement — every orchestrator, interactive or Phase 1's headless
  `claude -p`, must run with its working directory set to the target repo
  root. Only relevant while bitfactory and a target repo are being
  developed side by side, as they are now; dissolves once bitfactory itself
  is finished and each run just operates on one target repo directly.
- **Headless invocations require the workspace to be marked trusted
  first, separately from `.claude/settings.json`.** Claude Code's
  one-time folder-trust dialog can't be shown in headless mode; if
  `hasTrustDialogAccepted` isn't already `true` for that project path in
  `~/.claude.json`, **every `permissions.allow` entry gets silently
  ignored** — with `--permission-mode dontAsk`, that means everything gets
  denied. Found during Phase 1's first headless attempt: the planner
  claimed a ticket (staged the `git mv`, never got to commit it) and
  stalled there, since nothing after that was permitted. Fix: run Claude
  Code interactively in the target repo once and accept the trust dialog,
  or set `projects["<path>"].hasTrustDialogAccepted: true` directly in
  `~/.claude.json`. Machine- and path-specific — not something a repo's
  own `settings.json` can carry, so it has to be established once per
  machine/environment before headless runs there, separately from
  anything checked into the repo.
- **`git push`/`pull` need a real git credential helper configured —
  not the `-c http.extraHeader=...` flag used manually throughout this
  project so far.** That flag changes a command's prefix (`git -c ...
  push` instead of `git push`), which stops matching a plain
  `Bash(git push origin *)` allow rule — Claude Code's permission
  patterns match on literal command structure. Found when the tester
  correctly diagnosed this itself mid-run rather than forcing a
  workaround: it had no way to authenticate `git push origin main` under
  `dontAsk`, since `git config *` isn't allow-listed either (so it
  couldn't set up a helper on its own) and `tea` wasn't installed. Fix:
  configure a credential helper once, locally, per repo/machine —
  `git config credential.helper '!f() { echo username=token; echo
  "password=$GIT_FORGE_TOKEN"; }; f'` — so a plain, unprefixed
  `git push`/`git pull` just authenticates transparently, matching the
  existing allow rule without needing special-casing. Lives in
  `.git/config`, not tracked by either repo, same category as the
  trust-dialog fix above: one-time environment setup, not something
  either repo's files can carry.

## Concurrency

- **Max 3 tickets in `in_progress/` at once (v1).**
- **Max 3 worker agents running in parallel per ticket (v1).**
- **No separate token/cost budget per ticket for v1** — the retry cap (below)
  is the only cost bound for now. *Revisit when:* Phase 0 shows what a real
  ticket actually costs, or a ticket burns unexpectedly high cost without
  hitting the retry cap.

## Definition of done / human gate

- **Approval gate triggers on priority: high-priority tickets require human
  approval before `in_testing/ → done/`; low and medium go dark
  automatically** once tests pass and acceptance criteria are judged met —
  unless the second trigger below also applies.
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
- **The gate has a second, independent trigger: manual verification.**
  Priority and testability are orthogonal — a low-priority ticket can still
  have an acceptance criterion no agent can check mechanically (e.g. "the
  Tkinter main window opens and displays the dashboard layout correctly").
  The gate fires if `priority == high` **or** the ticket has
  `needs_manual_verification: true`, whichever applies; either reason routes
  through the same PR-review mechanism, with the PR description telling the
  human what to actually go check. This is deliberately *not* done by
  forcing such tickets to `priority: high` — that would misrepresent a
  routine UI tweak's urgency just to get it reviewed.
  - Criteria expected to need manual verification are tagged inline with
    `(manual)` by the planner while decomposing the ticket; the ticket-level
    `needs_manual_verification` frontmatter field is set `true` if any
    criterion is tagged.
  - The tester can also set the flag `true` during validation if it
    discovers an *untagged* criterion it genuinely can't verify itself —
    the planner's tagging is a best-effort first pass, not the only chance
    to catch this.

## Git and merging

- **Subtasks that unavoidably touch the same file still run in parallel;
  conflicts are resolved at merge time**, not by serializing them upfront.
  This happens during the planner's serialized-merge step (architecture.md),
  which also answers who owns conflict resolution: the **planner**, during
  integration — the tester never sees an unresolved conflict, only the
  already-integrated feature branch.
- **That policy doesn't extend to tickets stuck waiting on a human PR
  review.** A same-ticket subtask conflict resolves within one quick
  planner pass; a ticket gated on `priority: high` or
  `needs_manual_verification: true` (see above) can sit in `in_testing/`
  for an unbounded, human-dependent amount of time, during which several
  other tickets could land on `main` — raising real odds of a stale, hard
  (or silently wrong) conflict once that PR finally merges. **The planner
  holds a new ticket instead of claiming it** if its footprint looks likely
  to overlap a currently-open PR — see
  [architecture.md](architecture.md#cross-ticket-conflict-avoidance) for the
  mechanism. Scoped only to PR-gated tickets, not ordinary `in_progress/`
  ones, which merge quickly on their own and don't carry this risk.

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

- **planner and tester are bitfactory-specific agents** — written, and
  verified working end to end (Phase 0, then Phase 1 headless) — that
  delegate implementation work to generic installed role agents rather
  than doing it themselves.
- **v1 worker roster confirmed as proposed** in
  [../agents/README.md](../agents/README.md) — backend-developer,
  frontend-developer, fullstack-developer, language-specific `*-pro` agents,
  test-automator, code-reviewer, database-optimizer/sql-pro,
  git-workflow-manager. Expand deliberately as real tickets show a need for
  an uncovered role, not preemptively.

## Application code layout

- **Generated code lives in a dedicated directory (`src/` + `src/tests/`
  for Python targets), never at the target repo's root.** Found the root
  getting cluttered after three tickets each dropped their files there,
  with nothing separating them from the ticket-store/tooling directories.
  The planner states the target layout explicitly in each subtask's
  description (per-target-repo stack, not assumed); the tester's
  mechanical check needs the same convention to find the test command. See
  [architecture.md](architecture.md#application-code-layout) for the
  concrete Python default and why it's `unittest discover -t src`, not a
  `PYTHONPATH=` env-var prefix (same permission-pattern-matching pitfall
  as the git-push fix above).
