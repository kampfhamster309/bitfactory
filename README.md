# bitfactory

Experiment in building an agent-based "dark factory" for software: user
stories go into a backlog, and a pipeline of Claude Code agents (planner →
workers → tester) plans, implements, tests, and merges them with as little
human involvement as possible.

Status: **design phase** — no automation implemented yet. See
[docs/roadmap.md](docs/roadmap.md) for what "implemented" will mean at each
phase.

## Start here

- [docs/overview.md](docs/overview.md) — vision, goals, and a sanity check of
  the original workflow draft (worth reading first — several risks in the
  original design shaped everything else here).
- [docs/architecture.md](docs/architecture.md) — the v1 design: ticket
  format, git branching model, concurrency/locking, validation protocol.
- [docs/decisions.md](docs/decisions.md) — the resolved design decisions
  (concurrency caps, retry cap, gate policy, and so on) with rationale.
- [docs/open-questions.md](docs/open-questions.md) — the one thing not yet
  decided (the orchestrator trigger mechanism); check here before assuming
  it's settled.
- [docs/glossary.md](docs/glossary.md) — terms used throughout these docs.
- [docs/roadmap.md](docs/roadmap.md) — phased build-out, Phase 0 through 5.
- [agents/README.md](agents/README.md) — which agents play which role.

## Directory layout

```
backlog/       new tickets, not yet planned
in_progress/   claimed by the planner, being implemented
in_testing/    all subtasks merged, tester is validating
done/          validated and merged
agents/        agent-role documentation (planner/tester defs go here later)
docs/          planning docs (this is what you're reading)
```

A ticket's directory is its status — see
[docs/architecture.md](docs/architecture.md#ticket-lifecycle).

## Ticket format

Copy [docs/ticket-template.md](docs/ticket-template.md) into `backlog/` to
file a new ticket. Bug tickets use the same format with a `bug_` filename
prefix, per [docs/architecture.md](docs/architecture.md#ticket-id-and-file-format).
