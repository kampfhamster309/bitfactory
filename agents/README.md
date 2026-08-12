# bitfactory — Agent Roster

Two different kinds of agent are involved, and they shouldn't be confused:

## Factory-role agents (bitfactory-specific — not yet created)

`planner` and `tester` are the only agents that need to understand
bitfactory's ticket file format, directory state machine, and git branch
conventions. They don't yet exist as concrete Claude Code agent definitions
— that's the first real implementation task (see
[../docs/roadmap.md](../docs/roadmap.md) Phase 0). They're expected to live
as project-level agents, e.g. `.claude/agents/planner.md` and
`.claude/agents/tester.md`, and to **delegate** actual implementation work to
the worker roles below rather than writing code themselves.

## Worker agents (implementation — reuse what's installed)

This machine already has the `voltagent-*` subagent plugins installed
(visible to Claude Code as `voltagent-<category>:<role>`), covering roughly
150 role agents across core-dev, lang, infra, data-ai, qa-sec, dev-exp,
domains, biz, meta, and research categories. These are generic — they know
nothing about bitfactory's ticket protocol — which is exactly why they're a
good fit as workers: the planner assigns a subtask to one of them, they do
the implementation + tests in their worktree, and report back per the
protocol in [../docs/architecture.md](../docs/architecture.md#agent-report-back-protocol).

The full catalog (~150 roles) is too large for the planner to choose from
usefully. Confirmed v1 roster
([decisions.md](../docs/decisions.md#agent-roster)) — expand deliberately as
real tickets show a need for an uncovered role, not preemptively:

| Subtask kind | Role agent |
|---|---|
| Backend / API implementation | `voltagent-core-dev:backend-developer` |
| Frontend / UI implementation | `voltagent-core-dev:frontend-developer` |
| Full-stack feature (small ticket, one worker) | `voltagent-core-dev:fullstack-developer` |
| Language-specific implementation | `voltagent-lang:<language>-*` (e.g. `python-pro`, `typescript-pro`, `golang-pro`) — planner picks based on the repo's stack |
| Test authoring / test suite work | `voltagent-qa-sec:test-automator` |
| Code review pass (optional, before merge) | `voltagent-qa-sec:code-reviewer` |
| Database/schema changes | `voltagent-data-ai:database-optimizer` or `voltagent-lang:sql-pro` |
| Git/branch mechanics the planner needs help with | `voltagent-dev-exp:git-workflow-manager` |

This table is a starting point, not a lock-in — add rows as real tickets
show a need for a role not listed here.
