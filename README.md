# bitfactory

Experiment in building an agent-based "dark factory" for software: user
stories go into a backlog, and a pipeline of Claude Code agents (planner →
workers → tester) plans, implements, tests, and merges them with as little
human involvement as possible.

Status: **Phase 0 validated** — the planner/tester agents
([agents/README.md](agents/README.md)) and `scripts/ticket.py` exist and
have driven two tickets end to end against a sandbox target repo, one
through the plain path and one through the PR-gated
(`needs_manual_verification`) path. Still fully interactive/manual — no
orchestrator loop yet. See [docs/roadmap.md](docs/roadmap.md) for what's
next (Phase 1: headless invocation).

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
agents/        worker roster + symlinked planner/tester agent definitions
docs/          planning docs (this is what you're reading)
scripts/       ticket.py — file/validate tickets before they land in backlog/
```

A ticket's directory is its status — see
[docs/architecture.md](docs/architecture.md#ticket-lifecycle).

## Ticket format

File a new ticket with `scripts/ticket.py new` (flags or interactive
prompts — run `scripts/ticket.py new --help` for the flags) rather than
writing the file by hand: it generates the collision-safe ULID-prefixed id,
fills out the frontmatter correctly, and self-validates before writing into
`backlog/`. Bug tickets use `--bug-of <original-ticket-id>`, which also
auto-computes `retry_count` from the original.

`scripts/ticket.py validate <path>` checks an existing (e.g. hand-edited)
ticket file against the same rules. [docs/ticket-template.md](docs/ticket-template.md)
documents the schema itself, per
[docs/architecture.md](docs/architecture.md#ticket-id-and-file-format), for
reference or for filing one by hand if you'd rather.

## License

[MIT](LICENSE) — use any of it, an acknowledgement is appreciated but not
required.
