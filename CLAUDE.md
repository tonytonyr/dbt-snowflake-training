# CLAUDE.md — Project Context

Auto-loaded by Claude Code at session start. Read this file first, then
`SPEC.md`, `DECISIONS.md`, and `AI_WORKFLOW.md` in that order.

---

## Project Conventions

**Commits:** Conventional Commits — `<type>(<scope>): <description>`
Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`

**Branches:** GitHub Flow — `<type>/<short-description>` off `main`
Types: `feature/`, `fix/`, `chore/`, `docs/`

**Decisions:** Recorded in `DECISIONS.md` as ADRs. Settled decisions are not
re-litigated unless the engineer explicitly says "reopen ADR-XXX".

**Agent sync:** `.agents/` is source of truth. `.opencode/prompts/` is derived.
Run `python scripts/sync_agents.py --check` to verify sync state.

---

## Current Phase

**Phase 1 — Operational Store & E-Commerce Simulator**

Status: Phase 0 complete. Ready to begin Phase 1.
First action: Architect reviews and approves the state machine design before
Platform Engineer begins implementation.

---

## Session Notes

### 2026-06-02 — Phase 0 session
Completed: Phase 0 fully delivered. GitHub remote created at
`https://github.com/tonytonyr/dbt-snowflake-training`. Branch protection
enabled on `main` (PR required, no direct push). Two PRs merged:
PR #1 `feature/phase-0-github-setup` — pre-commit config, SQLFluff config,
PR template. PR #2 `chore/gitignore-cleanup` — excluded `lessons/`,
`.skill-evals/`, `.claude/` from version control. Stale branches
(`feature/phase-0-github-setup`, `chore/gitignore-cleanup`) can be deleted
locally. `lessons/phase-0/github-setup.md` written (gitignored, local only).
No SQL linter added for Postgres — Snowflake dialect only, intentional (see
lessons doc). No new ADRs this session — ADR-001 through ADR-012 all active.
Next: Begin Phase 1. Architect must review and approve the state machine
design (order lifecycle: placed→confirmed→shipped→delivered→returned) before
Platform Engineer starts `simulator/state_machine.py`.
Open: None.
