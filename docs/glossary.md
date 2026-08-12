# bitfactory — Glossary

**Ticket** — A markdown file with YAML frontmatter representing one unit of
work: a user story, acceptance criteria, priority, and (once planned) a
subtask breakdown. Lives in exactly one of `backlog/`, `in_progress/`,
`in_testing/`, `done/` (or `needs_human/`) at a time; its directory is its
status.

**Bug ticket** — An ordinary ticket with a `bug_` filename prefix, filed by
the tester agent when validation fails. Carries `bug_of` (the ticket it was
filed against) and `retry_count`.

**Feature branch** — The git branch for one ticket as a whole:
`feature/<ticket-id>`. Created by the planner, merged into by workers'
subtask branches, validated by the tester.

**Subtask branch** — A git branch for one worker's piece of a ticket:
`feature/<ticket-id>/subtask-<n>`, branched off the feature branch. Merged
back into the feature branch by the planner once the worker reports done.

**Worktree** — A separate git working directory (`git worktree`) checked out
to a subtask branch, giving one worker an isolated filesystem to edit in
without colliding with other workers or the planner. One worktree per
in-flight subtask.

**Planner (agent)** — The bitfactory-specific agent that claims tickets from
`backlog/`, decomposes them into subtasks, assigns subtasks to worker roles,
creates the feature branch, and serially merges finished subtask branches
into it. The only agent that moves a ticket into `in_progress/`.

**Worker (agent)** — An agent that implements one subtask (code + tests) in
its own worktree and reports completion back to the planner. Mostly the
existing installed role agents (e.g. `backend-developer`, `python-pro`),
not bitfactory-specific — see [../agents/README.md](../agents/README.md).

**Tester (agent)** — The bitfactory-specific agent that takes over once every
subtask on a ticket is merged: moves the ticket to `in_testing/`, runs the
full suite, judges the result against the original acceptance criteria, and
either moves the ticket to `done/` or files a bug ticket.

**Orchestrator** — The process/loop that actually drives the pipeline over
time: notices claimable tickets, invokes the planner, dispatches workers,
invokes the tester. Not yet a fixed component — see
[open-questions.md](open-questions.md#orchestration) for what it should be.

**Dark run** — An orchestrator run with the human-approval gate (see
architecture.md) turned off: tickets can reach `done/` with no human review.

**Supervised run** — An orchestrator run with the human-approval gate turned
on: at least one point in the pipeline (by default, `in_testing/ → done/`)
waits for a human before proceeding.

**Retry cap** — The maximum number of times a ticket lineage (original +
its `bug_` descendants) can loop through validation failure before the
tester escalates to a human instead of filing another bug ticket.
