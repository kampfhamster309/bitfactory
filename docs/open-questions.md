# bitfactory — Open Questions

Most of the questions originally tracked here have been resolved — see
[decisions.md](decisions.md) for the full log. One is deliberately still
open.

## Orchestrator trigger mechanism

**What actually invokes the planner/tester steps, and on what trigger?**

Deliberately left undecided, staged as:

1. **Phase 0** — fully interactive: this Claude Code session drives each
   step by hand.
2. **Phase 1** — headless (`claude -p`), but triggered manually or by a
   simple script; not yet committed to either.
3. **Final decision deferred** until the pipeline moves off the pure
   filesystem ticket store (Phase 4, external ticket sources) — the right
   trigger mechanism likely depends on what's driving intake at that point
   (a webhook from GitHub/Jira vs. a polling script vs. something else), so
   deciding it now would be guessing ahead of the information that should
   determine it.

*Blocks:* nothing in Phase 0. Relevant again once Phase 1 needs a concrete
answer for "what runs this without a human typing a command."

Nothing else is currently blocking implementation — if a new question comes
up during Phase 0, add it here.
