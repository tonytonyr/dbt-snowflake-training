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

**Phase 0 — GitHub Setup & Project Foundation**

Status: Foundation files built. Waiting on:
1. Engineer creates GitHub remote and pushes `main` (Step 1)
2. Engineer enables branch protection (Step 3)
3. Feature branch `feature/phase-0-github-setup` opened as first PR (Step 4)

---

## Session Notes

### 2026-06-02 — Phase 0 session
Completed: Baseline review, spec and agentic framework assessed as ready.
`INITIAL_SPEC.md` moved to `archived/`. Full agentic framework committed to
`main` (21 files, 2,732 insertions). Foundation files built: `.gitignore`,
`README.md`, `CLAUDE.md`. Feature branch files built: `.pre-commit-config.yaml`,
`.sqlfluff`, `.github/pull_request_template.md`. Lessons doc written at
`lessons/phase-0/github-setup.md`.
Decisions: ADR-001 through ADR-012 all active — no new decisions this session.
Next: Engineer completes Steps 1 and 3 (GitHub remote + branch protection),
then opens `feature/phase-0-github-setup` as the first PR and merges it.
Open: Confirm `node_modules/` in `.gitignore` is sufficient for `.opencode/`
deps or whether a nested `.gitignore` is needed there.
