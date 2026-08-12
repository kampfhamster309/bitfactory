# bitfactory — Overview

## Vision

An agent-based "dark factory" for software: user stories flow in as tickets,
and a pipeline of Claude Code agents plans, implements, tests, and integrates
them with as little human involvement as possible. The long-term goal is a
factory that can run largely unattended, turning backlog items into merged,
tested code.

## Goals (v1 experiment)

- Prove out a file-system-based ticket pipeline (`backlog/ → in_progress/ →
  in_testing/ → done/`) that a set of Claude Code agents can drive end to end.
- Establish clear, inspectable hand-offs between agent roles (planner, worker,
  tester) so a human can audit what happened even in an unattended run.
- Keep every ticket's history visible in git: one feature branch per ticket,
  one sub-branch per subtask, real commits and merges — not just a chat log.
- Learn where the model (Claude Code agents/subagents) actually maps onto
  this workflow cleanly, and where it needs scaffolding (scripts, locks,
  orchestration) that isn't "just an agent."

## Non-goals (v1)

- No Jira/GitHub Projects *intake* integration yet — plain markdown files in
  `backlog/` are the only ticket source. (A git forge is still used earlier
  than that, for PR-based approval of high-priority tickets — the local
  Gitea instance for now, GitHub eventually — see
  [decisions.md](decisions.md#definition-of-done--human-gate) — that's a
  separate concern from ticket intake.)
- No devcontainers / full sandboxed execution environments yet — isolation
  starts at the git-worktree level.
- No CI/CD to production — `done/` is the end of the pipeline for now.
- No multi-repo / multi-service support — one repo, one factory.
- Not fully unattended from day one — see the human-gate discussion below
  and in [open-questions.md](open-questions.md).

## Sanity check of the original draft

The five-step draft is a reasonable shape for the pipeline, but a few things
in it don't survive contact with how git, the filesystem, and Claude Code
agents actually behave. Flagging these now so the architecture doc designs
around them instead of discovering them mid-implementation:

1. **The filesystem *is* a shared queue, and queues need concurrency
   control.** "Planner picks up a new ticket from `backlog/`" is fine with
   one planner running at a time. The moment two planner runs (or a planner
   and a human) touch `backlog/` concurrently, you get double-picked tickets
   or half-moved files. Needs an explicit locking/claiming mechanism (e.g.
   atomic rename as claim, or a lockfile), even in v1.

2. **Parallel agents can't share one working directory.** Step 3 says agents
   work "ideally in an isolated environment like their own sub-branch" — that
   "ideally" needs to be a hard requirement. Two agents editing files
   concurrently in the same checkout will stomp on each other's uncommitted
   changes regardless of which branch they intend to commit to. Isolation
   means a separate `git worktree` (or clone) per agent per subtask, not just
   a separate branch name. Claude Code's `Agent` tool already supports
   `isolation: "worktree"`, which maps onto this requirement directly.

3. **"Available agents" is undefined.** The draft assumes the planner can
   assign subtasks to "available agents," but availability implies a
   concurrency limit and a scheduler. Without a cap, the factory will try to
   fan out a ticket into as many parallel agents as there are subtasks, with
   no bound on cost or on how many worktrees/branches exist at once.

4. **Auto-merging by the planner needs a conflict policy.** Step 4 has the
   planner merge every finished sub-branch back into the feature branch.
   That's fine when subtasks touch disjoint files; it silently breaks down
   the moment two subtasks touch the same file. Either subtasks must be
   scoped to non-overlapping files/modules by the planner, or the planner
   needs a real conflict-resolution step (which may itself need to be an
   agent invocation, not a plain `git merge`).

5. **"Tests pass" and "matches the user story" are different kinds of
   validation.** The testing agent in step 5 is asked to both run the test
   suite and judge whether the result satisfies the original acceptance
   criteria. The first is mechanical; the second is a judgment call. Worth
   naming that distinction explicitly so a green test suite doesn't get
   treated as automatic proof the story was actually fulfilled.

6. **The bug loop has no termination condition.** "If tests fail, create a
   `bug_` ticket and start over" is correct as a happy-path description, but
   as written it can loop forever on a ticket that the factory keeps failing
   to fix correctly. Needs a retry cap per ticket lineage, after which it
   escalates to a human instead of generating another `bug_` ticket.
   (Resolved: cap of 3, see [decisions.md](decisions.md#failure-handling).)

7. **Sequential numbering will collide.** Numbered markdown files
   (`001-...md`) work fine for one contributor adding tickets by hand, but
   collide easily once the bug loop, a human, and (later) an external
   integration can all create tickets. Prefer a scheme that's collision-safe
   by construction (e.g. timestamp or ULID prefix) even though sequential
   numbers are more human-friendly to skim.

8. **"Dark factory" and "unattended from day one" are not the same goal.**
   Nothing in the draft blocks agents from merging and marking tickets
   `done` without any human ever looking at the diff. That's the right
   long-term goal, but starting there means the first bug is discovered by
   whatever's downstream of `done/`. v1 makes the human gate a config
   option that gets relaxed as trust in the pipeline grows, rather than
   being absent by default. (Resolved: two independent triggers — priority
   and testability. High-priority tickets, and any ticket with an
   acceptance criterion no agent can verify mechanically, require PR
   approval on the local Gitea instance (for now); everything else goes
   dark automatically. See
   [decisions.md](decisions.md#definition-of-done--human-gate).)

None of these are reasons not to build this — they're the reason to design
the state machine and git model deliberately instead of letting "an agent
does it" stand in for "there is a concurrency-safe protocol for it." See
[architecture.md](architecture.md) for how v1 addresses each of these, and
[decisions.md](decisions.md) for the concrete choices made for each risk
above (concurrency caps, retry cap, gate policy, and so on). Only one
question remains genuinely open — see
[open-questions.md](open-questions.md).

## Refined high-level workflow (v1)

1. **Intake.** A ticket is added to `backlog/` as a markdown file with a
   collision-safe ID, a user story, acceptance criteria, and a priority.
   Bug reports are ordinary tickets with a `bug_` filename prefix.
2. **Planning.** A planner agent claims one ticket at a time (atomic move out
   of `backlog/`), breaks it into subtasks scoped to non-overlapping
   files/areas where possible, assigns each subtask to a worker role, creates
   the ticket's feature branch, writes the plan back into the ticket file,
   and moves the ticket into `in_progress/`.
3. **Implementation.** Each assigned worker agent runs in its own isolated
   git worktree/sub-branch off the feature branch, implements its subtask
   plus tests, and reports completion back to the planner.
4. **Integration.** On each subtask completion, the planner merges that
   sub-branch into the ticket's feature branch, one merge at a time
   (serialized, so conflicts are attributable to a single change).
5. **Validation.** Once every assigned subtask is merged, a tester agent
   moves the ticket into `in_testing/`, runs the full test suite on the
   feature branch, and separately judges the result against the original
   acceptance criteria.
   - Pass → ticket moves to `done/` automatically, unless it's
     high-priority or has an acceptance criterion no agent can verify
     mechanically — either one means it waits for PR approval on the local
     Gitea instance first (see
     [decisions.md](decisions.md#definition-of-done--human-gate)).
   - Fail → a new `bug_`-prefixed ticket is filed in `backlog/`, referencing
     the original ticket and a retry count; after 3 failed attempts on one
     lineage, escalate to a human instead of re-looping.
