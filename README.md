# bitfactory

Experiment in building an agent-based "dark factory" for software: user
stories go into a backlog, and a pipeline of Claude Code agents (planner →
workers → tester) plans, implements, tests, and merges them with as little
human involvement as possible.

Status: **Phase 3.5** — the planner/tester agents
([agents/README.md](agents/README.md)) and `scripts/ticket.py` have driven
thirteen tickets end to end against a sandbox target repo: single-purpose
tests covering the plain path, the PR-gated (`needs_manual_verification`)
path, a fully unattended headless (`claude -p`) run, real concurrent
worker dispatch, and priority-aware ticket selection — plus a real small
multi-ticket project (a Flask + TypeScript counter web app) with genuine
inter-ticket dependencies, run mostly headlessly with human PR review at
each gated step. That project surfaced several real gaps only sustained,
less-synthetic use turns up — see
[docs/roadmap.md](docs/roadmap.md#phase-35--a-real-multi-ticket-project-and-knowledge-sources).
Also added: pointing a ticket at an external
[knowledge source](#knowledge-sources) for grounding in real reference
material. See [docs/roadmap.md](docs/roadmap.md) for what's next
(Phase 4: external ticket sources).

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
auto-computes `retry_count` from the original. Real dependencies on
another ticket use `--depends-on <ticket-id>` (repeatable).

`scripts/ticket.py validate <path>` checks an existing (e.g. hand-edited)
ticket file against the same rules. [docs/ticket-template.md](docs/ticket-template.md)
documents the schema itself, per
[docs/architecture.md](docs/architecture.md#ticket-id-and-file-format), for
reference or for filing one by hand if you'd rather.

`scripts/ticket.py next` (Phase 3) picks which `backlog/` ticket to claim
next — highest priority first, FIFO within the same priority, among
tickets whose `depends_on` are satisfied — respecting the `in_progress/`
concurrency cap via `--cap` (default 3).

`scripts/ticket.py check-prs` checks every `in_testing/` ticket's open PR
against Gitea and reports which are merged — the detection an
orchestrator needs to actually notice a PR-gated ticket is ready to
finish, rather than depending on a human happening to check by hand. Run
this before `next` every orchestrator cycle — see
[docs/roadmap.md](docs/roadmap.md#phase-1--headless-still-single-threaded).

## Permission configuration

[docs/settings.json.example](docs/settings.json.example) is the template
for `.claude/settings.json` in a target repo — required before Phase 1
headless invocation (`claude -p`) so it doesn't stall on permission
prompts nobody's there to answer. See
[docs/architecture.md](docs/architecture.md#permission-configuration) for
what it does and doesn't cover.

## Knowledge sources

A ticket can point at an external Obsidian vault (plain Markdown +
frontmatter + `[[wikilinks]]`) for grounding in real reference material —
workers read it directly, no bespoke tooling, no RAG/embeddings. Bitfactory
doesn't create, populate, or manage the vault; that's out of scope. Needs
`$KNOWLEDGE_VAULT_PATH` set in the shell profile and a matching
`Read(//<path>/**)` rule in the target repo's `.claude/settings.json`. See
[docs/architecture.md](docs/architecture.md#knowledge-sources) for the
full design, including two things confirmed by testing rather than
assumed (subagent env-var inheritance, `Read` permission scope).

## License

[MIT](LICENSE) — use any of it, an acknowledgement is appreciated but not
required.
