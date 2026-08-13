# bitfactory — Architecture (v1)

This describes the v1 design, addressing the risks raised in
[overview.md](overview.md#sanity-check-of-the-original-draft). It's the
target to build toward, not a description of what's implemented yet — see
[roadmap.md](roadmap.md) for sequencing.

## Components

| Component | Role |
|---|---|
| **Ticket store** | The `backlog/`, `in_progress/`, `in_testing/`, `done/` directories. The pipeline's state machine — a ticket's location *is* its status. |
| **Orchestrator** | The process that drives the loop: notices new/claimable tickets, invokes the planner, dispatches workers, invokes the tester. Always a single instance (see [decisions.md](decisions.md#orchestration)). What triggers it — interactive session, manual headless invocation, or a script — is the one thing still deliberately undecided; see [open-questions.md](open-questions.md). |
| **Planner agent** | Owns ticket decomposition, subtask assignment, feature-branch creation, and serialized merges of finished sub-branches. The only agent that moves tickets `backlog/ → in_progress/`. |
| **Worker agents** | Do the actual implementation + tests for one subtask, in an isolated worktree, then report back. Mostly the existing installed role agents (see [../agents/README.md](../agents/README.md)) — not bitfactory-specific. |
| **Tester agent** | Owns final validation. Moves tickets `in_progress/ → in_testing/`, runs the full suite, judges against acceptance criteria, moves to `done/` or files a `bug_` ticket. |
| **Git** | One feature branch per ticket, one sub-branch per subtask, real commits/merges. Source of truth for what changed, independent of the ticket files. |

## Ticket lifecycle

```mermaid
stateDiagram-v2
    [*] --> backlog: intake (human or bug loop)
    backlog --> in_progress: planner claims ticket,\ncreates feature branch,\nwrites plan + assignments
    in_progress --> in_progress: workers finish subtasks,\nplanner merges each\nsub-branch serially
    in_progress --> in_testing: all subtasks merged
    in_testing --> done: full suite passes AND\nacceptance criteria met\n(+ PR approval if priority=high\nor needs_manual_verification)
    in_testing --> backlog: failure → new bug_ ticket\n(references original, retry count++)
    done --> [*]
```

A ticket's directory location is always authoritative for its status — the
ticket file's own frontmatter (`status:`) is a convenience mirror for
grepping, not the source of truth. This avoids the class of bug where the
file says one thing and its location says another.

## Ticket ID and file format

- **ID scheme:** `<ULID-or-timestamp>-<slug>.md`, e.g.
  `01J8Z3K9F7-add-csv-export.md`. Sortable by creation time, collision-safe
  without coordination, still skimmable via the slug. (Addresses sanity-check
  point 7 — sequential numbers collide once bugs/humans/future integrations
  can all create tickets concurrently.)
- **Bug tickets:** same scheme with a `bug_` prefix on the slug, e.g.
  `01J8Z4...-bug_csv-export-crashes-on-empty-input.md`.
- **Frontmatter (YAML):**

```yaml
---
id: 01J8Z3K9F7-add-csv-export
status: backlog        # mirrors directory location, see note above
priority: medium        # low | medium | high
created: 2026-08-12
source: human            # human | bug-loop | (future) jira | github
bug_of: null              # ticket id this bug was filed against, if any
retry_count: 0            # bumped each time the bug loop re-files this lineage
feature_branch: null      # set by planner
subtasks: []               # populated by planner, see below
depends_on: []             # ticket ids that must be status: done before this can be claimed
needs_manual_verification: false   # true if any criterion below is tagged (manual)
pr_url: null              # set by tester when it opens a PR; the signal an open,
                          # unresolved PR exists for the cross-ticket conflict check
---

## User story
As a ..., I want ..., so that ...

## Acceptance criteria
- [ ] ...
- [ ] The main window opens and displays the dashboard layout correctly (manual)
```

- **`(manual)` tag on an acceptance criterion:** marks a criterion no agent
  can check mechanically — typically something visual/interactive (a GUI
  actually rendering, layout looking right) rather than a property a test
  can assert. The planner tags these while decomposing the ticket; if any
  criterion is tagged, `needs_manual_verification` is set `true` in the
  frontmatter. The tester can also set it `true` later if it finds an
  *untagged* criterion it genuinely can't verify itself — the planner's
  pass is best-effort, not the only chance to catch this
  ([decisions.md](decisions.md#definition-of-done--human-gate)).

- **`depends_on:`** — a flow-style list of ticket ids (`[]` when there are
  none), set at filing time via `scripts/ticket.py new --depends-on <id>`
  (repeatable). `scripts/ticket.py next` filters out any backlog ticket
  whose `depends_on` isn't fully satisfied — satisfied means a ticket
  with that exact id sits in `done/` with `status: done`, not merely
  present in `done/`: a *failed* ticket also ends up in `done/`, but with
  `status: superseded` (see [decisions.md](decisions.md#failure-handling)),
  which does not count. The planner re-checks this itself during Job A
  before claiming, the same defense-in-depth reasoning as the
  cross-ticket conflict hold below — `next` already filtered, but a
  ticket could in principle be handed to the planner directly rather than
  picked via `next`. **Known limitation:** this is a literal id match,
  not a lineage match — if a depended-on ticket gets superseded and
  replaced by a `bug_` ticket, anything depending on the original id
  stays permanently blocked rather than automatically transferring to the
  replacement. Not solved for v1; revisit if it turns out to matter in
  practice.

- **`subtasks:` entry shape** (added by the planner during planning):

```yaml
subtasks:
  - id: 1
    description: "Add CSV export endpoint"
    assigned_role: voltagent-core-dev:backend-developer
    branch: subtask/01J8Z3K9F7-add-csv-export/1
    status: pending          # pending | in_progress | done | failed -- planner sets this from the worker's report, not the worker itself
    worktree: null            # path, set when the worker starts
    merged: false             # set true by the planner once integrated (Job B)
```

## Git branching model

- One **feature branch** per ticket: `feature/<ticket-id>`.
- One **subtask branch** per worker, off the feature branch:
  `subtask/<ticket-id>/<n>` — a separate top-level namespace from
  `feature/<ticket-id>`, not nested under it. Git branch refs are
  hierarchical (like filesystem paths), so a ref can't be both a leaf and a
  directory prefix for another ref: `feature/<ticket-id>/subtask-<n>` would
  collide with `feature/<ticket-id>` itself and simply cannot be created
  once the feature branch exists. Discovered the hard way during Phase 0's
  first walkthrough, not anticipated at design time.
- Each worker gets its own **git worktree** checked out to its subtask
  branch — never a shared checkout. This is what actually delivers the
  "isolated sub-branch" requirement from the original draft; a branch name
  alone doesn't prevent two agents from clobbering each other's uncommitted
  changes in a shared working directory.
- The planner **serializes merges**: subtask branches are merged into the
  feature branch one at a time, in the order workers report completion, not
  in parallel. This makes any conflict attributable to exactly one merge and
  avoids a class of race where two concurrent merges both look clean in
  isolation but conflict with each other.
- Where possible, the planner scopes subtasks to non-overlapping
  files/modules specifically to keep merges conflict-free by construction.
  When that's not possible (e.g. two subtasks both touch a shared config
  file), the planner still dispatches them in parallel rather than
  serializing them upfront — the overlap is resolved when it actually shows
  up as a conflict during the planner's serialized merge step, not guessed
  at during planning ([decisions.md](decisions.md#git-and-merging)). This
  also means **conflict resolution is a planner responsibility**: it happens
  during integration, before the tester ever sees the feature branch.
- The tester agent works directly on the feature branch (no further
  worktree needed — it's validating the integrated result).

## Dispatching workers

The orchestrator dispatches a worker by invoking it as an agent pointed at
the worktree path the planner already created and reported
(`worktrees/<ticket-id>/subtask-<n>`) — **without** requesting the
harness's own worktree isolation for that invocation (e.g. Claude Code's
`Agent` tool has an `isolation: "worktree"` option; leave it unset here).
Passing it anyway makes the harness spin up a *second*, separate worktree
of its own for the subagent, distinct from the one bitfactory's planner
already created — the two isolation mechanisms collide: the worker's
git/write operations get scoped to the harness's worktree, not
bitfactory's, so it can't commit onto the actual `subtask/<ticket-id>/<n>`
branch directly. bitfactory's own per-subtask worktree already *is* the
isolation; the harness doesn't need to add another layer on top. Found
during Phase 0 — the worker still produced correct work, just on a stray
branch that had to be cherry-picked onto the right one by hand instead of
landing there directly.

**Tell the worker not to chain Bash commands with `&&`/`;`/`|`** — issue
one command per tool call instead. `.claude/agents/planner.md` and
`tester.md` already follow this by construction, but a generic worker
role from the installed roster doesn't know it going in, and a chained
command can get denied outright under `dontAsk` (see
[Worker guardrails](#worker-guardrails) below). Worth including in every
worker's dispatch prompt, not just discovered after a denial.

## Application code layout

Generated code goes in a dedicated directory, never at the target repo's
root alongside the ticket-store directories (`backlog/`, `in_progress/`,
etc.) or bitfactory's own tooling (`docs/`, `.claude/`, `scripts/`,
`agents/`). Mixing "the product being built" in with "the factory
operating on it" gets confusing fast once more than a couple of tickets
have landed — found this from three tickets' worth of files sitting
directly at repo root with nothing separating them from the pipeline's
own scaffolding.

**Default for Python target repos: `src/` for code, `src/tests/` for
tests.** No real packaging needed (no `setup.py`/`pyproject.toml`) — just
`src/tests/__init__.py` so `unittest discover` can find it, and:

```
python3 -m unittest discover -s src/tests -t src
```

`-t src` adds `src/` to the import path so a test can do
`from hostname_check import get_hostname` without any `PYTHONPATH`
environment-variable prefix. That's deliberate, not a style preference:
an env-var prefix (`PYTHONPATH=src python3 ...`) changes what the command
literally starts with, which breaks a plain `Bash(python3 *)` permission
match the same way `-c http.extraHeader=...` broke `git push` (see
[decisions.md](decisions.md#orchestration)) — `unittest`'s own `-t` flag
avoids that class of bug entirely rather than needing a special-cased
permission rule.

Other stacks get their own idiomatic equivalent (e.g. `src/`/`__tests__/`
for Node) — the planner decides this per target repo's actual stack when
decomposing a ticket, and should say so explicitly in each subtask's
description so the assigned worker doesn't default to the repo root out
of habit. The tester's mechanical check ([below](#validation-protocol-tester-agent))
needs to know the same convention to find and run the right test command.

## Worktrees and locally-provisioned environments

A git worktree only gives you the repo's *tracked* content — anything
gitignored (a Python `.venv/`, `node_modules/`, and similarly for other
stacks) exists solely in whichever checkout it was created in, and isn't
copied or linked into new worktrees automatically. This matters because a
worktree's whole purpose in this pipeline is worker/tester isolation
([Git branching model](#git-branching-model) above) — but it means a
locally-provisioned environment set up once at the repo root (a venv,
`npm install`'s `node_modules/`, etc. — the same category of one-time,
outside-of-ticket-work environment setup as the workspace-trust and
credential-helper fixes, see [decisions.md](decisions.md#orchestration))
is invisible from inside every worktree by default.

Found this the concrete way: a worker in one worktree hit a missing
`.venv` and hand-copied packages into a local one to work around it; the
tester, in a different worktree, independently found and used a symlink
instead. Different agents solving the same gap two different ways is
exactly the outcome the earlier `cd`/`-C`/prefix-matching fixes were
trying to prevent elsewhere — the fix belongs at the point the worktree is
created, not left for whoever hits the gap first to improvise around.

**Fix:** the planner symlinks any such locally-provisioned directory
into each new worktree right after creating it (both the integration
worktree and every subtask worktree) —
`ln -s "$(pwd)/.venv" "<worktree-path>/.venv"` (see `planner.md` Job A).
This is deliberately a *symlink into the existing environment*, not a
fresh install per worktree: reinstalling dependencies per worktree would
work too, but wastes time and disk for something the root checkout
already has, and risks a subtly different environment per worktree if a
`pip install`/`npm install` run behaves even slightly differently each
time. After symlinking, every command inside a worktree can use the same
relative path (`.venv/bin/python`, etc.) that already works at the repo
root — no absolute paths or special-cased commands needed downstream, and
no new permission rules beyond the existing relative-path ones.

## Concurrency and locking

- **Claiming a ticket:** the planner claims a ticket by moving its file out
  of `backlog/` — on a POSIX filesystem, `rename(2)` is atomic, so this
  doubles as the lock. Exactly one orchestrator/planner loop runs at a time
  in v1 ([decisions.md](decisions.md#orchestration)), which is what makes
  this simple lock sufficient.
- **Ticket concurrency cap: 3.** At most 3 tickets in `in_progress/`
  simultaneously, so the factory doesn't fan out unboundedly across the
  whole backlog at once. Configurable, not hardcoded — 3 is the v1 default.
- **Subtask concurrency cap: 3.** At most 3 worker agents running in
  parallel on a single ticket, same reasoning.

## Cross-ticket conflict avoidance

The planner's conflict handling above covers subtasks *within* one ticket,
resolved quickly during that ticket's own integration step. It doesn't
cover a different risk: a ticket gated at the [human gate](#human-gate)
(`priority: high` or `needs_manual_verification: true`) can sit in
`in_testing/` for an unbounded, human-dependent amount of time with its
feature branch not yet merged into `main`. Other tickets can keep landing
on `main` during that wait, raising the odds that the gated branch is hard
— or silently wrong — to merge once it's finally approved
([decisions.md](decisions.md#git-and-merging)).

Before claiming a new ticket (Job A, step 2 in the planner), the planner
checks for this:

1. Find tickets in `in_testing/` with `pr_url` set (not `null`) — these are
   the ones actually waiting on human review; an ordinary `in_testing/`
   ticket the tester is still actively validating isn't a concern, since
   that resolves within one tester pass, not an open-ended wait.
2. For each one, get its exact touched-files list:
   `git diff main...<its feature_branch> --name-only`.
3. Compare that list against the new ticket's user story for plausible
   overlap (mentioned file paths, module/feature names). This is
   necessarily a heuristic — the new ticket hasn't been decomposed yet, so
   its own touched files aren't known — but the open PR's file list is
   exact, which is the useful half of the comparison.
4. If overlap looks likely: **hold** the new ticket. Leave it in
   `backlog/` (don't claim it), append a Log entry naming which open PR it
   conflicts with, and commit that note on `main`. No overlap, or no
   PR-gated tickets currently open: claim proceeds normally.

This isn't a guarantee — it reduces the odds of a bad stale conflict, it
doesn't replace the existing "resolved at merge time" policy for whatever
still slips through. There's no separate polling loop for this yet: the
hold is simply re-evaluated the next time the planner is invoked to claim
that ticket, whatever triggers that (see
[open-questions.md](open-questions.md#orchestrator-trigger-mechanism)).

## Crash recovery

If the orchestrator is interrupted with a ticket mid-flight in
`in_progress/` (some subtasks merged, maybe an open worktree), the planner
resumes automatically on restart by re-deriving what's left to do from the
ticket's `subtasks[]` state and the feature branch's git history — no human
triage required by default. This relies on the ticket file always being
updated *before* a worktree is torn down (the planner's job, per the
report-back protocol below), so `subtasks[]` is a reliable source of truth
to resume from.

## Agent report-back protocol

A worker reports completion by:
1. Committing its work on its subtask branch (including tests) — entirely
   within its own worktree.
2. Reporting completion (or failure, with why) back to whoever invoked it.
   **The worker never edits the ticket file itself** — that file is shared
   state across all of a ticket's subtasks, and writing to it isn't scoped
   to the worker's own worktree. (An earlier version of this protocol had
   the worker do this directly; found during Phase 0 that it both violates
   the worker-guardrails write-scope below and risks a race if two
   subtasks on the same ticket finish around the same time and both try to
   edit the same file.)
3. Leaving the worktree in place until the planner has merged it (the
   planner cleans up worktrees after a successful merge).

**The planner records `status: done`** (or `failed`) on the relevant
`subtasks[]` entry, as the first step of Job B ([planner.md](../.claude/agents/planner.md))
— based on the worker's report plus its own verification that the
worktree actually has committed work. This keeps the ticket file's only
writer, for subtask bookkeeping, as the planner: one writer, no race,
and workers stay fully inside their own worktree with no carve-out needed.

## Worker guardrails

Workers run unattended (no human watching each tool call), so v1 defaults to
**tight guardrails rather than full interactive permissions**
([decisions.md](decisions.md#isolation-and-safety)):
- Bash access is allowlisted, not open-ended.
- No unrestricted network access.
- Writes are scoped to the worker's own worktree, full stop — including the
  ticket file itself (see report-back protocol above); a worker never has
  a reason to touch anything outside its worktree.

Loosen these deliberately per-role only when a specific worker genuinely
needs more (e.g. a role that must run a package manager against a real
registry), not as a blanket default.

**Issue one command per Bash call, not `&&`/`;`/`|`-chained compounds.**
Claude Code parses compound commands and requires *every* sub-command to
independently match an allow rule — a chain fails outright if even one
piece isn't covered, which is a deliberate security property (stops a
disallowed command from smuggling itself in after an allowed-looking
first one), not a bug to route around. A generic worker role (not one of
bitfactory's own agents, which don't chain commands) hit this — its
first attempt chained `git add ... && git commit ...`, which was denied.
Whether that specific chain should have worked (both halves individually
match this repo's allow rules) is genuinely unclear — it wasn't cleanly
reproduced, since the reproduction attempt happened to include `echo`,
which was never allow-listed at all, so that attempt is fully explained
without needing the chaining mechanism to be broken. Rather than debug
which is true, the simple, safe fix is procedural: don't chain. Issue
`git add ...` and `git commit ...` (or whatever the sequence is) as
separate Bash tool calls — this sidesteps the ambiguity regardless of
its cause, and matches Claude Code's own documented intent (an approved
compound command gets saved as a separate rule per sub-command, not one
rule for the whole chain).

## Secrets

The git-forge token (the local Gitea PAT for now, a GitHub PAT once the
pipeline earns that per [decisions.md](decisions.md#definition-of-done--human-gate))
is the only credential the pipeline currently needs, and it follows the same
least-privilege boundary as the guardrails above:

- **Scope:** repo access only, no admin rights on the Gitea instance —
  narrower than "throwaway instance" might tempt you into, since the token
  is still a real credential at rest.
- **Storage:** an untracked, gitignored local file or env var (or the `tea`
  CLI's own config file) — never committed, never pasted into a ticket file,
  a doc, or a script argument that'd land in shell history.
- **Who holds it:** only the planner and tester agents, since they're the
  only roles that push branches or open/merge PRs. Workers never need it —
  it's out of scope for the worker guardrails above by construction, not
  because it's separately allowlisted away from them.
- **Never logged:** it must not leak into a ticket's `## Log` section or any
  persisted command output, the same way the guardrails above keep worker
  actions from writing outside their worktree.
- **How `git push`/`pull` actually use it: a git credential helper, not a
  command-line flag.** `git config credential.helper '!f() { echo
  username=token; echo "password=$GIT_FORGE_TOKEN"; }; f'`, configured
  once per repo/machine — reads the token fresh from the env var each
  time, never writes it to disk. Deliberately *not* the
  `-c http.extraHeader="Authorization: token $GIT_FORGE_TOKEN"` flag used
  manually earlier in this project: that flag changes the command's
  prefix, which breaks a plain `Bash(git push origin *)` permission match
  under `--permission-mode dontAsk` (see
  [decisions.md](decisions.md#orchestration)). PR creation via `curl` is
  unaffected — the token there is a header *argument*, not a wrapping
  flag, so it doesn't change what the command starts with.

Storing it this way now (env var / gitignored file, planner+tester only,
never persisted) means switching from the Gitea token to a real GitHub PAT
later is a value swap in the same slot, not a rethink of how secrets flow
through the pipeline.

## Permission configuration

The guardrails and secrets scoping above are *decisions*; this is what
turns them into something Claude Code actually enforces. [`settings.json.example`](settings.json.example)
is the template — copy it to `.claude/settings.json` in the target repo
and adjust before Phase 1 headless invocation (a working copy already
exists in the sandbox target used for Phase 0).

- **What it allows:** the concrete git/worktree operations planner and
  tester actually use (`mv`, `add`, `commit`, `branch`, `worktree add/remove`,
  `merge`, scoped `push`/`pull` to `origin` only), `scripts/ticket.py`,
  running the target repo's own code/tests, and network access narrowed to
  one specific git-forge host (`curl https://YOUR-GIT-FORGE-HOST/*` —
  **edit this placeholder per target repo**, it's the one line that can't
  be copied verbatim). Writes are scoped to the ticket-store directories
  and `worktrees/**` — nowhere else, via `Edit(path/**)` rules only.
  (There's no separate `Write(path/**)` permission — Claude Code's own
  file-permission checks only look at `Edit` rules, which cover every
  file-editing tool; a `Write(...)` entry is silently never matched.
  Found this from Claude Code's own warning on a real headless run and
  dropped the dead entries rather than leaving them as confusing noise.)
- **What it denies, explicitly (defense in depth):** force-push, hard
  reset, force branch deletion, `rm -rf`, `sudo`, and `WebFetch`. Deny
  rules always win over allow rules, so these stay blocked even if a
  future allow rule accidentally overlaps.
- **The `python3 *` / `python -m *` allow entries are stack-specific to
  this template's sandbox target.** They exist so the tester can actually
  run the target repo's test suite and workers can run the app — swap them
  for whatever the target repo's real stack needs (`npm test`, `go test`,
  etc.) rather than assuming Python.
- **No `defaultMode` is set.** Deliberately — setting `"defaultMode": "dontAsk"`
  in the committed file would apply to *interactive* sessions too, silently
  auto-denying anything outside the allowlist instead of prompting a human
  who's right there watching (exactly the situation Phase 0 has mostly been
  run in so far). Headless invocations (Phase 1) should pass
  `--permission-mode dontAsk` explicitly on the command line instead, so
  interactive use keeps its normal safety net and only headless runs get
  the strict auto-deny behavior.
- **None of this matters until the workspace is trusted.** This file's
  `permissions.allow` rules are silently ignored entirely — not just for
  the specific unmatched action, *all of them* — if the target repo's
  path doesn't already have `hasTrustDialogAccepted: true` in
  `~/.claude.json`. Headless mode can't show the one-time trust dialog to
  get that set, so it has to be established beforehand: run Claude Code
  interactively in the target repo once and accept it, or set that field
  directly. This is machine-and-path-specific state, not something this
  repo's `settings.json` can carry — see
  [decisions.md](decisions.md#orchestration) for how this was found (a
  headless run stalled with a ticket half-claimed, not obviously connected
  to trust at first).
- **This isn't adversarial-proof, and isn't meant to be.** It stops the
  clearly dangerous stuff (destructive git ops, arbitrary network egress)
  and reduces prompt friction for the well-worn path; it doesn't stop a
  worker from running an allowed git command it wasn't supposed to use.
  That boundary is enforced by each agent's own instructions (`.claude/agents/*.md`)
  plus the human review at the PR gate, not by this file — consistent with
  treating these as cooperative agents following documented procedure, not
  something being defended against active misuse.
- **Every allow rule for a git subcommand is listed three times: plain,
  `git -C <path> <subcommand>`, and `cd <path> && git <subcommand>`.**
  Permission patterns match on literal command prefix, so a plain
  `Bash(git commit *)` rule doesn't cover `git -C worktrees/.../commit`
  or `cd worktrees/... && git commit` — agents need one or the other
  whenever they're not already in the right directory (e.g. the planner
  operating on a subtask's worktree from the repo root). Found on a
  headless run: it worked around the gap itself (routing through
  `subprocess.run(cwd=...)` under the broad `python3 *` allow) rather
  than getting stuck, but a workaround succeeding once isn't something to
  rely on, especially unattended — so all three forms are allow-listed
  explicitly now. **Every deny rule got the same three-way treatment**,
  for the same reason in the other direction: a bare `Bash(git branch -D *)`
  deny doesn't catch `git -C <path> branch -D <name>` or
  `cd <path> && git branch -D <name>` either — an unprefixed deny rule
  is exactly as bypassable via `-C`/`cd &&` as an unprefixed allow rule
  is unusable, so broadening the allow list without broadening the deny
  list the same way would have quietly reopened the force-push/hard-reset/
  branch-deletion/`rm -rf`/`sudo` holes it exists to close.
- **`python -m *` needs the same `cd <path> &&` form as `python3 *`, not
  just the plain one.** These two allow rules were added at different
  times and ended up asymmetric: `Bash(python3 *)` got a matching
  `Bash(cd * && python3 *)`, but `Bash(python -m *)` didn't get
  `Bash(cd * && python -m *)`. A worker running
  `cd <worktree> && python -m unittest ...` hit exactly that gap and,
  rather than getting stuck, worked around it via `python3 -c` invoking
  `unittest`'s loader API directly. The workaround produced a correct
  result, but "found a way around a permission denial" isn't something
  to leave standing as the expected path — it's the same reasoning as the
  `git`/subprocess workarounds above: close the actual gap instead of
  relying on an agent improvising past it, especially unattended. Fixed
  by adding the missing `cd * &&` form; **whenever a new plain `Bash(...)`
  allow rule is added, add its `cd * && ...` counterpart in the same
  change**, not as a follow-up once something hits the gap.

## Validation protocol (tester agent)

Two distinct checks, reported separately rather than collapsed into one
pass/fail:
1. **Mechanical:** run the full test suite (existing tests + everything
   workers added) on the feature branch.
2. **Judgment:** re-read the original user story and acceptance criteria and
   assess whether the merged result actually satisfies them — a green suite
   doesn't by itself prove this, especially for acceptance criteria that
   weren't turned into an automated test. If a criterion turns out to be
   something the tester genuinely can't verify itself, even though it
   wasn't tagged `(manual)` at planning time, it sets
   `needs_manual_verification: true` rather than guessing at a pass/fail —
   this is what routes the ticket through PR review regardless of priority.

Both must pass for the ticket to move to `done/`. A failure in either
produces a `bug_` ticket describing which check failed and why.

## Bug loop and retry cap

- A `bug_` ticket filed by the tester sets `bug_of: <original-id>` and
  `retry_count: <n+1>`, carrying the count forward from the ticket it
  replaces.
- A max retry count of **3** causes the tester to escalate to a human
  instead of filing another bug ticket, by leaving the ticket in a
  `needs_human/` directory rather than looping back to `backlog/`
  ([decisions.md](decisions.md#failure-handling)).

## Human gate

`in_testing/ → done/` uses a gate with **two independent triggers**
([decisions.md](decisions.md#definition-of-done--human-gate)) — either one
routes the ticket through PR review instead of straight to `done/`:
- **Priority:** `priority: high`.
- **Testability:** `needs_manual_verification: true` — the ticket has at
  least one acceptance criterion no agent can check mechanically (see the
  `(manual)` tag convention above).

These are deliberately kept separate rather than folded into priority: a
routine, low-priority UI tweak can still need a human to actually look at
it, without that forcing its priority up just to get reviewed. **Low- and
medium-priority tickets with no `(manual)` criteria** go straight to
`done/` automatically once the full suite passes and acceptance criteria
are judged met.

Approval happens via **PR/MR review on a git forge**: the ticket's feature
branch is pushed and opened as a PR, and approval means the PR is
approved/merged. The PR description states *why* it's gated — priority,
manual-verification criteria (quoted directly, so the human knows exactly
what to go check — e.g. "confirm the main window opens and the dashboard
layout looks right"), or both. For Phase 0/1, this targets the **local
Gitea instance** (self-hosted on the Unraid server) rather than the
`origin` GitHub remote — an unattended run's PR-opening/merging can't touch
the real repo while the pipeline is still unproven. GitHub becomes the
target once the pipeline has earned that. Either way, **a git-forge remote
is needed as soon as any gated ticket reaches `in_testing/`** — worth
remembering even in Phase 0, since this dependency arrives earlier than the
GitHub *intake* integration work planned for Phase 4 (a separate concern
from using a forge for this approval step).

There is no earlier gate in v1 — the planner's subtask breakdown is not
reviewed before workers start; only this end gate exists.

### Noticing a PR has been approved

The tester's own procedure says what to do "when later told the PR was
approved/merged" — but nothing previously said *how* that news was
supposed to arrive. Every PR-gated ticket so far only got finished
because a human (or an orchestrator standing in for one) happened to
check the forge by hand and say so — there was no mechanism that
actually noticed on its own, which defeats the point for a genuinely
headless run.

`scripts/ticket.py check-prs` closes this: it checks every `in_testing/`
ticket with `pr_url` set against Gitea's API and reports which are now
merged. It's detection-only — it never touches git or ticket files
itself, the same separation of concerns as `next` (which picks a ticket
but doesn't claim it). **Every orchestrator cycle should run `check-prs`
before `next`** — finish whatever's ready before starting something new,
rather than leaving a merged PR sitting unfinished while the orchestrator
goes looking for new work instead (see
[roadmap.md](roadmap.md#phase-1--headless-still-single-threaded) for
where this fits into the actual cycle). If it reports a merged PR, the
orchestrator invokes the tester with that ticket id, telling it the PR is
merged — same shape as it's always been told, just triggered by a real
check instead of a human remembering to look.

Gitea-specific by construction (parses the PR's `html_url` shape to build
its API URL) — will need its own logic for GitHub once the pipeline
earns that swap, not just a host substitution.

## Logging / audit trail

Log lines in the ticket file are the only persisted audit trail for v1 — no
separate full-transcript storage per ticket
([decisions.md](decisions.md#observability)). Each ticket accumulates its
own history in one place so a human can reconstruct an unattended run after
the fact:
- Git history on the feature/subtask branches (the "what changed").
- A `## Log` section appended to the ticket markdown file by each agent as
  it hands off (the "who did what, and why") — timestamped entries, not a
  full transcript.
- Where an agent's reasoning matters beyond a log line (e.g. why the tester
  judged acceptance criteria unmet), that goes in the log entry directly
  rather than only living in an agent transcript that isn't persisted
  anywhere.
