#!/usr/bin/env python3
"""
Create and validate bitfactory tickets before they land in backlog/.

Stdlib-only by design: bitfactory has no dependency setup yet, and the
ticket frontmatter schema is small and fixed, so a general YAML library
would be more machinery than this needs. See docs/architecture.md#ticket-id-and-file-format
for the schema this mirrors, and docs/ticket-template.md for the plain
template this replaces for anyone who'd rather fill it out by hand.

Usage:
    scripts/ticket.py new --title "Add CSV export" --priority medium \\
        --story "As a user, I want to export my data as CSV, so that I can use it elsewhere." \\
        --criteria "Export button appears on the dashboard" \\
        --criteria "Clicking it downloads a valid CSV file"

    scripts/ticket.py new --title "Crash on empty input" --priority high \\
        --bug-of 01J8Z3K9F7-add-csv-export \\
        --story "..." --criteria "..."

    scripts/ticket.py new --title "Frontend UI" --priority medium \\
        --depends-on 01J8Z3K9F7-backend-api --story "..." --criteria "..."

    scripts/ticket.py new   # interactive, prompts for everything

    scripts/ticket.py validate backlog/01J8Z3K9F7-add-csv-export.md

    scripts/ticket.py next   # which backlog/ ticket to claim next (priority, then FIFO)

    scripts/ticket.py check-prs   # which in_testing/ tickets' PRs have been merged on Gitea
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKET_DIRS = ["backlog", "in_progress", "in_testing", "done", "needs_human"]
PRIORITIES = ("low", "medium", "high")
SOURCES = ("human", "bug-loop", "jira", "github")
DEFAULT_TICKET_CAP = 3   # matches decisions.md#concurrency's v1 default; configurable, not hardcoded there either

CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


# --- ID generation -----------------------------------------------------

def _encode_part(value: int, num_chars: int) -> str:
    """Encode an unsigned int as fixed-width Crockford base32, MSB first."""
    return "".join(
        CROCKFORD_ALPHABET[(value >> (i * 5)) & 0x1F]
        for i in range(num_chars - 1, -1, -1)
    )


def generate_ulid() -> str:
    """Standard ULID layout: 48-bit ms timestamp as 10 chars, then 80 bits
    of randomness as 16 chars -> 26 chars total, lexicographically sortable
    by creation time."""
    ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    return _encode_part(ts_ms, 10) + _encode_part(rand, 16)


def slugify(text: str, max_len: int = 40) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:max_len].rstrip("-") or "ticket"


# --- Rendering -----------------------------------------------------------

def render_ticket(
    ticket_id: str,
    priority: str,
    source: str,
    bug_of: str | None,
    retry_count: int,
    story: str,
    criteria: list[str],
    depends_on: list[str] | None = None,
) -> str:
    bug_of_val = "null" if bug_of is None else bug_of
    depends_on = depends_on or []
    lines = [
        "---",
        f"id: {ticket_id}",
        "status: backlog",
        f"priority: {priority}        # low | medium | high",
        f"created: {date.today().isoformat()}",
        f"source: {source}            # human | bug-loop | jira | github",
        f"bug_of: {bug_of_val}",
        f"retry_count: {retry_count}",
        "feature_branch: null",
        "subtasks: []",
        f"depends_on: [{', '.join(depends_on)}]   # ticket ids that must be status: done before this can be claimed",
        "needs_manual_verification: false   # set true if any criterion below is tagged (manual)",
        "pr_url: null              # set by tester when it opens a PR",
        "---",
        "",
        "## User story",
        story.strip(),
        "",
        "## Acceptance criteria",
    ]
    for item in criteria:
        lines.append(f"- [ ] {item.strip()}")
    lines += [
        '<!-- Tag a criterion "(manual)" if no agent can verify it mechanically,',
        '     e.g. "- [ ] The main window opens and looks right (manual)" -->',
        "",
        "## Log",
        "<!-- Agents append timestamped entries here as they hand off. -->",
        "",
    ]
    return "\n".join(lines)


# --- Parsing / validation -------------------------------------------------

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def parse_ticket(text: str, *, require_unplanned: bool = False) -> tuple[dict[str, str], str]:
    """Minimal parser for this tool's own fixed schema.

    By default this parses a ticket from any stage, including an already-
    `done` one with planner-populated subtasks (needed by --bug-of's
    retry-count lookup and by dependency checking, both of which routinely
    read completed tickets). Pass require_unplanned=True (validate_content's
    own use) to additionally enforce that subtasks is still the untouched
    `[]` a fresh backlog-stage ticket should have -- catches a ticket sitting
    in backlog/ that's inconsistently already been planned.
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("no --- frontmatter block found")
    fm_text, body = m.group(1), m.group(2)

    fields: dict[str, str] = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line[0].isspace():
            # Nested/continuation content under a top-level key -- e.g. a
            # subtask's own fields, or a multi-line `description: >` block
            # scalar the planner wrote. This schema's real top-level keys
            # are always unindented (single-line scalars, or depends_on's
            # flow-style list); anything indented belongs to a parent key
            # like `subtasks:`, not a new top-level field, so skip it
            # rather than trying to parse it as one. Found this the hard
            # way: a real planner-written subtask description used YAML's
            # `>` block-scalar syntax, which has no colon on its
            # continuation lines and was misidentified as a malformed
            # top-level line before this check existed.
            continue
        if ":" not in line:
            raise ValueError(f"unparseable frontmatter line: {line!r}")
        key, _, rest = line.partition(":")
        key = key.strip()
        value = rest.split("#", 1)[0].strip()
        if require_unplanned and key == "subtasks" and value != "[]":
            raise ValueError(
                "ticket already has planner-populated subtasks; this tool "
                "only creates/validates backlog-stage tickets"
            )
        fields[key] = value
    return fields, body


def parse_id_list(value: str) -> list[str]:
    """Parse a compact flow-style YAML list like '[]' or '[a, b, c]' --
    the format depends_on is rendered/read in, matching this file's
    stdlib-only, no-real-YAML-parser design."""
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError(f"expected a flow-style list like [] or [a, b], got {value!r}")
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [item.strip() for item in inner.split(",")]


def validate_content(text: str, filename: str) -> list[str]:
    errors: list[str] = []
    try:
        fields, body = parse_ticket(text, require_unplanned=True)
    except ValueError as e:
        return [str(e)]

    stem = filename[:-3] if filename.endswith(".md") else filename

    if fields.get("id") != stem:
        errors.append(f"id ({fields.get('id')!r}) doesn't match filename stem ({stem!r})")

    if fields.get("status") != "backlog":
        errors.append(f"status must be 'backlog', got {fields.get('status')!r}")

    if fields.get("priority") not in PRIORITIES:
        errors.append(f"priority must be one of {PRIORITIES}, got {fields.get('priority')!r}")

    if fields.get("source") not in SOURCES:
        errors.append(f"source must be one of {SOURCES}, got {fields.get('source')!r}")

    is_bug_filename = "-bug_" in stem
    bug_of = fields.get("bug_of")
    if is_bug_filename and bug_of in (None, "null"):
        errors.append("filename has a bug_ prefix but bug_of is null")
    if not is_bug_filename and bug_of not in (None, "null"):
        errors.append("bug_of is set but filename has no bug_ prefix")

    retry_count = fields.get("retry_count")
    if retry_count is None or not retry_count.isdigit():
        errors.append(f"retry_count must be a non-negative integer, got {retry_count!r}")

    if fields.get("feature_branch") != "null":
        errors.append("feature_branch must be null before planning")

    try:
        depends_on = parse_id_list(fields.get("depends_on", "[]"))
    except ValueError as e:
        errors.append(f"depends_on: {e}")
        depends_on = []
    for dep_id in depends_on:
        if dep_id == fields.get("id"):
            errors.append(f"depends_on lists this ticket's own id ({dep_id!r}) -- a ticket can't depend on itself")
        elif find_ticket_by_id(dep_id) is None:
            errors.append(f"depends_on references {dep_id!r}, which doesn't exist as a ticket anywhere")

    if fields.get("needs_manual_verification") not in ("false", "true"):
        errors.append("needs_manual_verification must be true or false")

    if fields.get("pr_url") != "null":
        errors.append("pr_url must be null before testing")

    story_match = re.search(r"## User story\s*\n(.*?)\n##", body, re.DOTALL)
    story = story_match.group(1).strip() if story_match else ""
    if not story or story == "As a ..., I want ..., so that ...":
        errors.append("User story section is empty or still the placeholder text")

    criteria = re.findall(r"^- \[ \] (.+)$", body, re.MULTILINE)
    if not criteria:
        errors.append("Acceptance criteria section has no '- [ ]' items")
    elif all(c.strip() == "..." for c in criteria):
        errors.append("Acceptance criteria are still placeholder text")

    return errors


def find_id_collision(ticket_id: str) -> Path | None:
    for d in TICKET_DIRS:
        for p in (REPO_ROOT / d).glob(f"{ticket_id}.md"):
            return p
    return None


def find_ticket_by_id(ticket_id: str) -> Path | None:
    for d in TICKET_DIRS:
        p = REPO_ROOT / d / f"{ticket_id}.md"
        if p.exists():
            return p
    return None


# --- PR status checking (Gitea) --------------------------------------------

GITEA_PR_URL_RE = re.compile(r"^(https?://[^/]+)/([^/]+)/([^/]+)/pulls/(\d+)$")


def gitea_pr_api_url(pr_url: str) -> str:
    """Convert a Gitea PR's html_url (e.g. http://host:port/owner/repo/pulls/3)
    into its REST API url. Gitea-specific by construction -- see
    decisions.md for the known limitation this leaves for a future
    GitHub swap (a different URL shape and API would need their own
    conversion, not handled here)."""
    m = GITEA_PR_URL_RE.match(pr_url.strip())
    if not m:
        raise ValueError(f"doesn't look like a Gitea PR URL: {pr_url!r}")
    base, owner, repo, number = m.groups()
    return f"{base}/api/v1/repos/{owner}/{repo}/pulls/{number}"


def check_pr_merged(pr_url: str) -> bool:
    """True if the given Gitea PR is merged, False if it's still open.
    Raises (ValueError, URLError, TimeoutError) if the check itself
    couldn't be completed -- callers should treat that as "couldn't
    determine," never assume unmerged just because the check failed."""
    api_url = gitea_pr_api_url(pr_url)
    req = urllib.request.Request(api_url)
    token = os.environ.get("GIT_FORGE_TOKEN")
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.load(resp)
    return bool(data.get("merged"))


# --- CLI -------------------------------------------------------------------

def prompt_missing(args: argparse.Namespace) -> None:
    if not sys.stdin.isatty():
        missing = [
            name
            for name in ("title", "priority", "story")
            if getattr(args, name) is None
        ]
        if missing or not args.criteria:
            missing_str = ", ".join(missing + (["criteria"] if not args.criteria else []))
            sys.exit(
                f"error: not running in a terminal, and required field(s) missing: "
                f"{missing_str}. Pass them as flags instead (see --help)."
            )
        return

    if args.title is None:
        args.title = input("Title (short, used to build the ticket ID): ").strip()
    if args.priority is None:
        while args.priority not in PRIORITIES:
            args.priority = input(f"Priority {PRIORITIES}: ").strip().lower()
    if args.story is None:
        args.story = input("User story (As a ..., I want ..., so that ...): ").strip()
    if not args.criteria:
        print("Acceptance criteria, one per line, empty line to finish:")
        args.criteria = []
        while True:
            line = input("- ").strip()
            if not line:
                break
            args.criteria.append(line)


def cmd_new(args: argparse.Namespace) -> int:
    prompt_missing(args)

    if args.priority not in PRIORITIES:
        sys.exit(f"error: --priority must be one of {PRIORITIES}")
    if not args.criteria:
        sys.exit("error: at least one --criteria is required")

    is_bug = args.bug_of is not None
    source = args.source or ("bug-loop" if is_bug else "human")

    retry_count = args.retry_count
    if is_bug and retry_count is None:
        original = find_ticket_by_id(args.bug_of)
        if original is None:
            sys.exit(
                f"error: --bug-of {args.bug_of!r} not found in any ticket "
                f"directory, and no --retry-count given to override"
            )
        orig_fields, _ = parse_ticket(original.read_text())
        retry_count = int(orig_fields.get("retry_count", "0")) + 1
    retry_count = retry_count or 0

    ulid = generate_ulid()
    slug = slugify(args.title)
    ticket_id = f"{ulid}-bug_{slug}" if is_bug else f"{ulid}-{slug}"

    collision = find_id_collision(ticket_id)
    if collision is not None:
        sys.exit(f"error: a ticket with id {ticket_id!r} already exists at {collision}")

    content = render_ticket(
        ticket_id=ticket_id,
        priority=args.priority,
        source=source,
        bug_of=args.bug_of,
        retry_count=retry_count,
        story=args.story,
        criteria=args.criteria,
        depends_on=args.depends_on,
    )

    filename = f"{ticket_id}.md"
    errors = validate_content(content, filename)
    if errors:
        print("error: generated ticket failed its own validation:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    out_path = REPO_ROOT / "backlog" / filename
    out_path.write_text(content)
    print(out_path.relative_to(REPO_ROOT))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        sys.exit(f"error: {path} does not exist")

    errors = validate_content(path.read_text(), path.name)
    if errors:
        print(f"{path}: INVALID")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"{path}: OK")
    return 0


def dependencies_met(depends_on: list[str]) -> bool:
    """A dependency is met only by a ticket sitting in done/ with
    status: done -- literal presence in done/ isn't enough, since a
    failed ticket also ends up there with status: superseded (see
    tester.md's "On fail"). If the depended-on ticket was superseded,
    its replacement bug_ lineage is what would actually need to reach
    done/ itself; this function doesn't walk that chain, it only checks
    the literal id given -- see decisions.md for this known limitation."""
    for dep_id in depends_on:
        dep_path = REPO_ROOT / "done" / f"{dep_id}.md"
        if not dep_path.exists():
            return False
        try:
            dep_fields, _ = parse_ticket(dep_path.read_text())
        except ValueError:
            return False
        if dep_fields.get("status") != "done":
            return False
    return True


def cmd_next(args: argparse.Namespace) -> int:
    """Pick which backlog/ ticket to claim next: highest priority first,
    FIFO (by ULID creation order) within the same priority, among tickets
    whose depends_on entries are all satisfied (status: done). Respects
    the ticket concurrency cap by checking in_progress/'s current size.

    Deliberately does NOT do the cross-ticket conflict check
    (architecture.md#cross-ticket-conflict-avoidance) -- that compares a
    specific ticket's likely file footprint against a specific open PR's
    actual diff, which needs the ticket already chosen and its content
    read. This command only answers "which ticket, if any" -- the
    planner still does that check itself during Job A after this.
    """
    in_progress_count = sum(1 for _ in (REPO_ROOT / "in_progress").glob("*.md"))
    if in_progress_count >= args.cap:
        sys.exit(
            f"error: at capacity -- {in_progress_count} ticket(s) already in "
            f"in_progress/ (cap: {args.cap}); nothing to claim right now"
        )

    backlog_paths = list((REPO_ROOT / "backlog").glob("*.md"))

    priority_rank = {p: i for i, p in enumerate(PRIORITIES)}
    candidates: list[tuple[int, str, Path]] = []
    for path in backlog_paths:
        try:
            fields, _ = parse_ticket(path.read_text())
        except ValueError as e:
            print(f"warning: skipping unparseable ticket {path.name}: {e}", file=sys.stderr)
            continue
        try:
            depends_on = parse_id_list(fields.get("depends_on", "[]"))
        except ValueError as e:
            print(f"warning: skipping ticket {path.name} with malformed depends_on: {e}", file=sys.stderr)
            continue
        if not dependencies_met(depends_on):
            continue
        rank = priority_rank.get(fields.get("priority"), -1)
        candidates.append((rank, path.name, path))

    if not candidates:
        if backlog_paths:
            sys.exit(
                "error: backlog/ has tickets, but none are eligible yet -- "
                "all have unmet depends_on entries"
            )
        sys.exit("error: backlog/ is empty -- nothing to claim")

    candidates.sort(key=lambda c: (-c[0], c[1]))
    _, _, chosen = candidates[0]
    print(chosen.relative_to(REPO_ROOT))
    return 0


def cmd_check_prs(args: argparse.Namespace) -> int:
    """Check every in_testing/ ticket with pr_url set against Gitea,
    reporting which are merged and ready for the tester to complete
    (see tester.md's "when later told the PR was approved/merged" step).

    This is a detection-only command -- it never touches git or ticket
    files itself. Nothing previously checked this automatically; every
    prior PR-gated ticket only got finished because a human (or an
    orchestrator standing in for one) happened to check by hand and say
    so. An orchestrator loop should run this before `next`, every cycle,
    so a merged PR gets finished before new work starts, rather than
    depending on someone remembering to check.

    Exit 0 if at least one ticket is confirmed merged (there's something
    to finish); exit 1 otherwise (nothing gated, nothing merged yet, or
    a check couldn't be completed) -- distinguishable from stdout, but a
    single non-zero code is enough for a caller to branch on.
    """
    gated: list[tuple[Path, str]] = []
    for path in (REPO_ROOT / "in_testing").glob("*.md"):
        try:
            fields, _ = parse_ticket(path.read_text())
        except ValueError as e:
            print(f"warning: skipping unparseable ticket {path.name}: {e}", file=sys.stderr)
            continue
        pr_url = fields.get("pr_url")
        if pr_url and pr_url != "null":
            gated.append((path, pr_url))

    if not gated:
        print("no in_testing/ tickets have an open PR to check")
        return 1

    any_merged = False
    for path, pr_url in gated:
        try:
            merged = check_pr_merged(pr_url)
        except (ValueError, urllib.error.URLError, TimeoutError) as e:
            print(f"COULD NOT CHECK  {path.relative_to(REPO_ROOT)}  {pr_url}  ({e})")
            continue
        if merged:
            print(f"MERGED  {path.relative_to(REPO_ROOT)}  {pr_url}")
            any_merged = True
        else:
            print(f"open    {path.relative_to(REPO_ROOT)}  {pr_url}")

    return 0 if any_merged else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a new ticket in backlog/")
    p_new.add_argument("--title", help="short title, used to build the ticket's slug")
    p_new.add_argument("--priority", choices=PRIORITIES)
    p_new.add_argument("--story", help="the user story")
    p_new.add_argument("--criteria", action="append", help="one acceptance criterion; repeat for more")
    p_new.add_argument("--bug-of", help="original ticket id, if this is a bug report")
    p_new.add_argument("--retry-count", type=int, help="override; default is looked up from --bug-of + 1")
    p_new.add_argument("--source", choices=SOURCES, help="default: human, or bug-loop if --bug-of is set")
    p_new.add_argument(
        "--depends-on", action="append", dest="depends_on",
        help="ticket id that must be status: done before this can be claimed; repeat for multiple",
    )
    p_new.set_defaults(func=cmd_new)

    p_val = sub.add_parser("validate", help="validate an existing ticket file")
    p_val.add_argument("path", help="path to the ticket file")
    p_val.set_defaults(func=cmd_validate)

    p_next = sub.add_parser("next", help="pick the next backlog/ ticket to claim (priority, then FIFO)")
    p_next.add_argument(
        "--cap", type=int, default=DEFAULT_TICKET_CAP,
        help=f"max tickets allowed in in_progress/ at once (default: {DEFAULT_TICKET_CAP})",
    )
    p_next.set_defaults(func=cmd_next)

    p_check_prs = sub.add_parser(
        "check-prs", help="check in_testing/ tickets' open PRs against Gitea for merges"
    )
    p_check_prs.set_defaults(func=cmd_check_prs)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
