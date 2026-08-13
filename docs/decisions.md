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
- **`settings.json`'s git allow/deny rules are each listed three ways:
  plain, `git -C <path> ...`, and `cd <path> && git ...`.** Permission
  patterns match literal command prefix, so agents working from a
  different directory than the repo root (routine for the planner,
  operating on a subtask's worktree) hit this whenever they don't
  literally type an unprefixed `git ...` from the repo root. A headless
  run found this and worked around it itself (`subprocess.run(cwd=...)`
  via the already-broad `python3 *` allow) rather than stalling — good
  that it could, but a workaround that happened to work once isn't
  something to depend on, especially with no human watching. Fixed by
  listing all three forms for every rule, allow *and* deny — an
  unprefixed deny doesn't catch the `-C`/`cd &&` forms of the same
  command either, so broadening allow without broadening deny the same
  way would have quietly reopened exactly the holes deny exists to close
  (force-push, hard reset, branch deletion, `rm -rf`, `sudo`). See
  [architecture.md](architecture.md#permission-configuration).
- **`Bash(python -m *)` needed its own `Bash(cd * && python -m *)`
  counterpart too** — it had been added without one, unlike `python3 *`,
  so a worker running `cd <worktree> && python -m unittest ...` hit the
  gap and worked around it (correctly, but via `python3 -c` instead of
  the intended command) rather than getting stuck. Fixed, and noted as a
  standing rule going forward: any new plain `Bash(...)` allow rule gets
  its `cd * && ...` counterpart added in the same change, not
  discovered later. See
  [architecture.md](architecture.md#permission-configuration).

## Concurrency

- **Max 3 tickets in `in_progress/` at once (v1).**
- **Max 3 worker agents running in parallel per ticket (v1).**
- **`scripts/ticket.py next` picks which backlog ticket to claim next**
  (Phase 3): highest priority first, FIFO within the same priority
  (ULID-ordered), enforcing the `in_progress/` cap above via `--cap`
  (default 3). Added because nothing did this before — every prior
  ticket was handed to the orchestrator explicitly by name; there was no
  actual selection logic anywhere despite priority being part of the
  ticket schema since v1.
- **`depends_on: []` on the ticket schema, filtered by `scripts/ticket.py
  next`.** Priority alone can't express "ticket B can't start until
  ticket A's API contract is real" — a real gap, hit while filing a
  small multi-ticket project (a Flask backend + TypeScript frontend)
  where the tickets had genuine dependencies, not just varying urgency.
  Set at filing time (`--depends-on <id>`, repeatable); `next` skips any
  backlog ticket whose dependencies aren't all `status: done` in `done/`
  (not merely present there — a superseded/failed ticket also ends up in
  `done/`, and doesn't count). The planner re-checks this itself during
  Job A too, same reasoning as the existing conflict-hold re-check.
  Known limitation, not solved for v1: this is a literal id match, so a
  superseded dependency permanently blocks its dependents rather than
  transferring to whatever `bug_` ticket replaced it. See
  [architecture.md](architecture.md#ticket-id-and-file-format).
- **Found and fixed while building `depends_on`: `parse_ticket()` had a
  latent bug that made the existing `--bug-of` retry-count auto-lookup
  silently broken against any real, already-`done` original ticket** —
  its subtasks-guard raised on any populated (non-`[]`) `subtasks:`
  field, which every ticket that's actually reached `done/` has, but the
  only prior test of that lookup used a still-`backlog` ticket, so this
  never surfaced. Fixed by making the guard opt-in
  (`parse_ticket(text, require_unplanned=True)`, used only by
  `validate_content`'s backlog-stage check) rather than baked into every
  call, since the new dependency check also needs to read arbitrary
  `done/` tickets without erroring on their populated subtasks. Verified
  both the fix and the original `--bug-of` path against a real
  populated-subtasks `done` ticket in a sandbox before touching the real
  target repo.
- **A second, more consequential `parse_ticket()` bug surfaced the moment
  `depends_on` was tried against a real planner-written `done` ticket**:
  the real planner (not my own hand-written test fixtures) wrote its
  subtask `description` using YAML's multi-line block-scalar syntax
  (`description: >` with indented continuation lines) rather than a
  single-line quoted string — perfectly valid YAML, but `parse_ticket()`'s
  line-by-line loop tried to parse every continuation line as its own
  `key: value` pair and raised on the first one without a colon. This
  isn't an edge case — it's what real planner output looks like once a
  description is long enough to want wrapping, so it would have kept
  silently breaking `depends_on` (and anything else reading `done/`
  tickets) going forward, not just this once. Fixed by skipping any
  frontmatter line with leading whitespace — this schema's real top-level
  keys are always unindented, so an indented line is by construction
  nested content under a parent key (`subtasks:`'s own fields, or a block
  scalar's continuation), never a new top-level field to parse. Re-ran
  the full sandbox regression suite after the fix to confirm nothing else
  broke.

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
- **`scripts/ticket.py check-prs` detects merged PRs; every orchestrator
  cycle runs it before `next`.** Real gap: tester.md always said what to
  do "when later told the PR was approved/merged," but nothing ever
  actually noticed on its own — every PR-gated ticket to date only got
  finished because a human (or me, standing in for one) checked the
  forge by hand. That's a real problem for genuinely headless operation.
  `check-prs` reads every `in_testing/` ticket's `pr_url`, checks it
  against Gitea, and reports which are merged — detection only, same
  separation of concerns as `next` (picks a ticket, doesn't claim it).
  The orchestrator cycle now runs it first, so finishing existing
  approved work always takes priority over starting something new. See
  [architecture.md](architecture.md#noticing-a-pr-has-been-approved) and
  [roadmap.md](roadmap.md#phase-1--headless-still-single-threaded).
  Gitea-specific (parses the PR's `html_url` shape); needs its own logic
  for GitHub, not just a host swap, once that migration happens.
- **`tester.md`'s `git mv` steps now explicitly say to update `status:`
  in the frontmatter alongside every directory move.** Found by a real
  headless run following `tester.md` literally: 3 of its 4 `git mv`
  steps (claim → `in_testing/`, pass → `done/`, and the delayed
  PR-approved → `done/` completion) never said to touch `status:` at
  all — only the `superseded` fail-path did, because that one needs a
  non-default value and so happened to get called out. Every ticket I'd
  hand-processed myself had a correct `status:` regardless, purely
  because I updated it out of habit each time — the gap only showed up
  once a real agent followed the literal instructions without that
  unwritten assumption. This isn't cosmetic: `scripts/ticket.py next`'s
  `dependencies_met()` check reads the frontmatter `status: done` field
  specifically, so a stale mirror doesn't just misinform a human grepping
  tickets, it can make a genuinely satisfied dependency look unmet.
  Confirmed two real tickets in the actual repo already had this
  staleness and fixed them directly. `docs/architecture.md`'s "directory
  is authoritative, frontmatter is a convenience mirror" framing only
  holds if the mirror is actually kept current — worth remembering if a
  future agent-authored procedure adds another directory move without
  this project's own habit of double-checking it.

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
- **The planner symlinks locally-provisioned, gitignored directories
  (a Python `.venv/`, etc.) into every new worktree it creates.** Found
  during the first backend ticket with a real dependency (Flask, via a
  provisioned `.venv/`): worktrees don't inherit gitignored content from
  the main checkout at all, so a worker and the tester each independently
  improvised a different workaround for the same missing `.venv` — one
  hand-copying packages, one symlinking on its own. Fixed at the source
  instead: the planner symlinks it in right after `git worktree add`, so
  every worktree just has it, and downstream commands keep using the same
  relative path (`.venv/bin/python`) that already worked at the repo
  root — no absolute paths, no new permission rules needed. See
  [architecture.md](architecture.md#worktrees-and-locally-provisioned-environments).
- **Workers issue one command per Bash call — no `&&`/`;`/`|` chaining.**
  Compound commands require every sub-command to independently match an
  allow rule (confirmed, documented Claude Code behavior, not a bug); a
  generic worker role hit a denial chaining `git add ... && git commit
  ...`, but the follow-up reproduction attempt happened to include
  `echo` (never allow-listed), so it doesn't cleanly confirm whether that
  *specific* chain should have worked. Rather than resolve the ambiguity,
  the fix is procedural and unconditionally safe: don't chain, issue
  separate Bash calls. Worth remembering that generic (non-bitfactory)
  worker roles don't know this convention going in the way `planner.md`/
  `tester.md` themselves already do — see
  [architecture.md](architecture.md#worker-guardrails).

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

## Knowledge sources

- **An Obsidian vault (plain Markdown + YAML frontmatter + `[[wikilinks]]`)
  is the supported format for grounding a ticket in real reference
  material, not a bespoke bitfactory format and not real RAG
  (embeddings/vector search).** Considered and rejected building an
  actual retrieval pipeline: the corpus this needs to support isn't
  reliably small (could be a personal CV or a company wiki), so "just
  read all the files" doesn't generalize — but the fix for that isn't
  embeddings, it's giving a worker Read/Grep tools and letting it explore
  the vault the way it already explores an unfamiliar codebase. Wikilinks
  beat a hand-maintained index file specifically because they're written
  *inline*, incrementally, as part of normal note-taking — a separate
  index would drift out of sync exactly like the ticket `status:` field
  did (see above). No bitfactory tooling to resolve links/frontmatter for
  v1; add it only if raw exploration proves insufficient for some future,
  much larger vault. **Vault existence and management (creation, syncing,
  content) is explicitly out of scope for bitfactory** — it's read-only
  external reference material, not something the pipeline provisions.
- **Two separate, confirmed-by-testing facts shaped how the vault is
  located, not assumption:**
  1. A dispatched worker subagent can't be assumed to inherit an env var
     set in the orchestrating session's shell (not explicitly documented,
     but the isolation signals point that way — a subagent gets a
     reduced system prompt and `cd` doesn't persist across its own tool
     calls). So `$KNOWLEDGE_VAULT_PATH` is resolved by the **planner**
     (part of the top-level flow, not a dispatched subagent) and passed
     to workers as a literal path in the subtask description — the same
     pattern already used for the `.venv` path and `src/` layout, not a
     new mechanism.
  2. A bare `"Read"` allow entry does **not** grant access outside the
     working directory — confirmed by actually testing it under
     `--permission-mode dontAsk`, not assumed from the settings.json
     syntax alone. Reading an external vault needs its own explicit
     `Read(//<absolute-vault-path>/**)` rule, a static, machine-specific
     literal path in `.claude/settings.json` (permission rules can't
     reference an env var at rule-definition time) — same category as
     the Gitea host already baked into the `curl` rule there. Set once
     per machine alongside `$KNOWLEDGE_VAULT_PATH`; keep both in sync by
     hand if the vault ever moves. See
     [architecture.md](architecture.md#knowledge-sources).
