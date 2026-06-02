# Phase 0 — GitHub Setup & Project Foundation

Learning notes for every element of Phase 0, written as each step executes.
The goal is not just *what* was done but *why* — the reasoning that makes each
choice defensible in a senior DE interview.

---

## 1. Repository Initialization Strategy

### What
The project was initialized locally first, then pushed to a remote — not created
on GitHub with an auto-generated README and cloned down.

### Why this order matters
GitHub's "Initialize this repository" option creates an initial commit on the
remote. If you also have local commits, you end up with **divergent histories**
and must force-push or rebase to reconcile them. Starting local avoids the
problem entirely: `git init` → commits → `git remote add` → `git push`.

The corollary for projects with existing code: always create the remote as an
**empty repository** (no auto README, no auto .gitignore, no auto license).

### Interview angle
This is a proxy question interviewers use to gauge git fluency. If you say "I
cloned from GitHub and added my files," that's fine for greenfield. But
explaining *why* you'd avoid the auto-init when you have prior commits shows
you understand how git history works, not just the happy path.

---

## 2. What Goes in `.gitignore` and Why

### What
A `.gitignore` was committed to `main` before branch protection was enabled,
covering four categories:

| Category | Patterns | Why |
|---|---|---|
| Python runtime | `__pycache__/`, `*.pyc`, `.venv/` | Generated files; differ per machine; no value in history |
| dbt artifacts | `target/`, `dbt_packages/`, `logs/`, `profiles.yml` | `target/` is compiled output (regenerated on `dbt run`); `profiles.yml` contains Snowflake credentials |
| Environment | `.env`, `.env.local` | **Secrets** — credentials, connection strings. The single most dangerous gitignore omission |
| OS/IDE | `.DS_Store`, `Thumbs.db`, `.vscode/settings.json` | Machine-local noise; pollutes PRs |

### The `.env` pattern
The project uses a two-file pattern common in professional DE repos:

- `.env` — actual credentials; **gitignored**
- `.env.example` — committed template showing every variable name with placeholder values

`.env.example` serves as living documentation: any new team member (or future
you) can `cp .env.example .env` and know exactly what to populate. The PR
checklist item "`.env.example` updated if new vars added" enforces that this
stays in sync.

### `profiles.yml` specifically
dbt's `profiles.yml` holds Snowflake account credentials and target schema
names. It lives outside the dbt project directory by default (`~/.dbt/`) for
exactly this reason — it should never be in version control. This project
keeps it inside the repo directory for Dev Container portability but gitignores
it, and commits `profiles.yml.example` instead.

### Why commit `.gitignore` before branch protection
Once branch protection is on, you cannot push directly to `main`. If `.gitignore`
isn't there yet, a developer could accidentally `git add .` and stage `.env` before
the protection rule exists. Committing `.gitignore` first closes that window.

---

## 3. README.md — Why a Stub, Not the Full Thing

### What
A minimal README with the project title, one-paragraph description, and tech
stack was committed at project start. Full documentation is Phase 6.

### Why stub first
The README is the first thing any visitor — recruiter, hiring manager,
interviewer — sees. An empty README signals an unfinished project. A stub with
a clear tech stack signals intent and scope even before the stack is built.

More practically: writing the full README before the stack exists means writing
fiction. Architecture diagrams, dbt lineage screenshots, and `docker compose up`
quickstart instructions are only accurate once those things exist. Writing them
at Phase 0 creates documentation debt — they'll be wrong by Phase 3.

The pattern: **stub early, fill late**. The Phase 6 polish step replaces the
stub with the real thing.

---

## 4. CLAUDE.md — The Project's Persistent Memory

### What
`CLAUDE.md` is auto-loaded by Claude Code at the start of every session. It
serves as the living context file: conventions, current phase, and session
handoff notes.

### Why this matters for an agentic workflow
Without a persistent context file, every AI session starts cold. The agent
reads the codebase but doesn't know:
- What was decided last session
- What was deliberately left out (and why)
- What the next action is

`CLAUDE.md` solves this. The `## Session Notes` section is appended (never
overwritten) at the end of every session by the Architect agent. Any model
that reads `SPEC.md` + `DECISIONS.md` + `CLAUDE.md` can reconstruct full
project context without a human briefing.

### The three sections
- `## Project Conventions` — commit format, branch naming, ADR format. Written
  once, rarely changed.
- `## Current Phase` — one line; updated at phase transitions.
- `## Session Notes` — append-only log. Each entry: date, what was completed,
  decisions made (with ADR references), and the *first action* of the next
  session. The next-action line is the most important — it is what prevents
  sessions from starting with "where were we?"

---

## 5. Branch Protection — Why Every Rule Exists

### What
Branch protection on `main` enforces four rules:
1. Require pull request before merging
2. Require at least 1 approving review
3. Require status checks to pass
4. Require branches to be up to date

### Rule-by-rule reasoning

**Require PR before merging**
Forces all changes through a review step. For a solo project this might feel
like ceremony — it is. The discipline is the point. On a team, a direct push to
`main` bypasses all quality gates and creates an irreversible (or painful to
reverse) event on the shared branch. The habit built here transfers directly.

**Require approving review**
On a solo project, you review your own PR. That sounds pointless but isn't:
the act of writing a PR description forces you to articulate *what changed and
why* before merging. It's a structured second look. On a team, it prevents the
"I'll just merge my own thing quickly" shortcut that bypasses knowledge sharing.

**Require status checks**
No CI exists in Phase 0, so the check list is empty. The rule is configured now
so that when GitHub Actions is added in Phase 3, the PRs that were already open
automatically inherit the new check requirement. You don't have to remember to
add the check requirement later.

**Require branches to be up to date**
Prevents a PR from merging if `main` has moved ahead since the branch was
created. Without this, two PRs can pass CI independently but conflict when
merged in sequence. This rule forces the second PR author to pull, rebase, and
re-verify — catching the conflict before it hits `main`.

### The hard gate in the sequence
Branch protection must be enabled *after* the foundation files reach `main`
and *before* any feature branch work begins. Once it's on, the first PR that
successfully opens, passes (no CI yet), and merges is the proof-of-concept
that the gate works.

---

## 6. Pre-commit Hooks — Shift-Left Quality

### What
`.pre-commit-config.yaml` runs four hooks on every `git commit`:
- `trailing-whitespace` — strips trailing spaces
- `end-of-file-fixer` — ensures files end with a newline
- `sqlfluff-lint` — lints `.sql` files against Snowflake dialect
- `yamllint` — validates YAML structure

### Why pre-commit over CI-only
CI lint catches issues after you push, which means:
1. You context-switch away from the code before seeing the failure
2. You push a commit that will require a fixup commit
3. Others see the broken state in CI if they pull the branch

Pre-commit catches the same issues at `git commit` time — before the code
leaves your machine. The fix happens in the same mental context as the original
change. Fixup commits never make it into the history.

The two approaches are complementary, not alternatives: pre-commit is the fast
local gate, CI is the authoritative gate that runs in a clean environment.

### SQLFluff dialect: snowflake
SQLFluff supports multiple dialects because SQL is not a single standard.
`QUALIFY`, `SAMPLE`, `FLATTEN`, `$1` positional column references — these are
Snowflake-specific syntax. Linting with the wrong dialect would produce false
positives on valid Snowflake SQL, or miss Snowflake-specific anti-patterns.

### Why `templater = dbt`
dbt models contain Jinja (`{{ ref('orders') }}`, `{% if ... %}`). SQLFluff
can't parse raw Jinja as SQL — it needs the dbt templater to resolve the Jinja
before linting the resulting SQL. Without this setting, every model with a
`{{ ref() }}` call would produce a lint error.

---

## 7. PR Template — Why Checklists Work

### What
`.github/pull_request_template.md` auto-populates the PR description field
whenever a new PR is opened against the repo.

### Why
Without a template, PR descriptions range from "fix stuff" to multi-paragraph
essays with no consistent structure. A template creates a minimum bar:
- **What changed and why** — forces the author to state intent, not just action
- **How to test locally** — reviewer can verify independently without reading
  every line of diff
- **Checklist** — externalizes the "did I forget anything" check that lives in
  every engineer's head

The checklist item "DECISIONS.md updated if architectural choice was made" is
specific to this project's agentic workflow. Without it, an agent could make an
architectural decision in a session and it would never get recorded — the next
session would start without knowing the decision was made.

### The discipline argument
A PR template is only as good as the culture around it. For a solo project,
"culture" means your own habits. The template is the commitment device: it's
harder to merge a PR with unchecked boxes than to skip filling out a template
that doesn't exist.

---

## 8. Conventional Commits — Why Format Matters

### What
All commits follow `<type>(<scope>): <description>`. Types: `feat`, `fix`,
`chore`, `docs`, `test`, `refactor`, `ci`.

### Why
A consistent commit format turns `git log` from a wall of text into a readable
project narrative. Compare:

```
# Without convention
fixed thing
wip
more fixes
actually working now
update

# With Conventional Commits
feat(simulator): add order state machine with lifecycle transitions
fix(staging): handle null actual_delivery in stg_retail__shipments
chore(deps): bump dbt-snowflake to 1.9.0
test(marts): add assert_order_totals_balance custom test
```

The second log tells a story. A recruiter reading the commit history of the
second repo sees a disciplined engineer. The first is noise.

Beyond aesthetics: tools like `semantic-release` and `conventional-changelog`
parse this format to auto-generate changelogs and version bumps. Adopting the
convention from the start means you can add those tools later without rewriting
history.

### Scope as signal
The `(scope)` component names the subsystem being changed. For this project:
`simulator`, `staging`, `intermediate`, `marts`, `cdc`, `airflow`, `ci`, `deps`.
When reviewing a PR or debugging a regression, filtering `git log` by scope
instantly isolates the relevant commits.

---

## 9. GitHub Flow — The Right Branching Strategy for This Project

### Why not Git Flow
Git Flow has `develop`, `release`, `hotfix`, and `feature` branches. It was
designed for software with versioned releases and parallel maintenance of
multiple released versions. A data pipeline has none of those properties —
there is one "production" state (the dbt project running against Snowflake) and
no concept of maintaining v1.x while developing v2.x.

Git Flow's ceremony would add two permanent long-lived branches, mandatory
merge commits, and a release tagging ritual — all overhead with no learning
return for this project.

### Why not trunk-based
Trunk-based development (direct commits to `main`, feature flags for incomplete
work) optimizes for speed in environments with very high CI confidence and
experienced teams who review each other's work asynchronously. The tradeoff is
that it eliminates the PR review step as a forcing function.

For this project, the PR review step *is* the learning contract. Every PR
forces: write the description, fill the checklist, get CI green, approve the
merge. Trunk-based would let you skip all of that.

### GitHub Flow: the right fit
One long-lived branch (`main`, always deployable). Short-lived feature branches,
merged via PR. Simple, linear, and the pattern used at most DE/analytics
organizations. Learning it here transfers directly to the target employers
(DoorDash, Instacart, Visa all use variants of this pattern).

---

## 10. The Two-Harness Agentic Framework

### What
Agent definitions live in `.agents/<role>.md` (Claude Code format) with
matching prompts in `.opencode/prompts/<role>.md` (OpenCode format). A sync
script and hooks keep them in sync automatically.

### Why not just use Claude Code memory
Claude Code's memory is session-local and Anthropic-dependent. If Anthropic has
an outage, the project stops. If the memory is cleared, context is lost.

The `.agents/` files are the persistent memory. Any model — Claude, Mistral,
DeepSeek — that reads `SPEC.md` + `DECISIONS.md` + `CLAUDE.md` can pick up
where the last session left off. The project files are the source of truth, not
the AI's context window.

### Why the model routing table
Not all tasks require the same model capability. Using a frontier model for
formulaic YAML generation wastes money and provides no quality improvement.
The routing table (`AI_WORKFLOW.md`) codifies these tradeoffs once so they
don't have to be re-decided on every task:

- Architecture, design, security → Claude Sonnet (reasoning-heavy)
- First implementation of a new pattern → Tier 1/2 (needs to get it right)
- Repeat pattern application → Tier 2 (established pattern, just apply it)
- Boilerplate, YAML, docs → Tier 3 (cheap, fast, sufficient)

The rule: AI earns its cost when it eliminates repetition, not when it replaces
thinking.

---

## Session Summary

**Phase 0 status:** Foundation complete. Waiting on engineer actions (Steps 1 and 3)
before feature branch work can begin.

**What was built in this phase:**
- `.gitignore` — protects secrets and generated files from accidental commit
- `README.md` — stub signals project intent to visitors
- `CLAUDE.md` — persistent context file for the agentic workflow
- `.pre-commit-config.yaml` — shift-left SQL and YAML linting
- `.sqlfluff` — Snowflake dialect + dbt templater configuration
- `.github/pull_request_template.md` — enforces PR discipline

**What this phase proves:**
Branch protection is active. Every subsequent phase change goes through a PR.
The full CI/CD loop (Phase 3) will layer on top of this gate — the gate itself
is already wired.

**Next phase:** Phase 1 — Postgres schema and e-commerce simulator.
First action: Architect reviews and approves the state machine design before
the Platform Engineer begins implementation.
