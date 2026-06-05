# AI Workflow & Model Routing

This document defines how AI tools are used across the project — which tasks go to which tools and models, and the learning contract that keeps AI assistance from becoming a crutch.

This is a living document. As models evolve, update the tier assignments and routing decisions here rather than in SPEC.md.

---

## Philosophy

AI handles execution of well-defined tasks. The engineer handles understanding, decision-making, and validation.

**The learning contract:**
- AI writes first drafts; you must be able to explain the output before it merges
- Architectural decisions are made in conversation with AI, not delegated to it
- Every PR description is written by the engineer — if you can't write it, you don't understand it yet
- The PR review step (`/code-review`) is a forcing function, not a formality

**The force multiplier rule:**
AI earns its cost when it eliminates repetition, not when it replaces thinking. Use expensive models for reasoning; use cheap models for pattern application.

---

## Tools

| Tool | Role |
|------|------|
| **Claude Code** | Architecture, design, debugging, security-sensitive work, PR reviews, project-wide context tasks |
| **OpenCode** | Implementation, pattern application, boilerplate — routed to appropriate model tier |

---

## Model Tiers

Tiers are based on capability profile, not cost alone. Update this section as new models become available or existing models are updated.

### Tier 1 — Near-Frontier
*Use for: complex reasoning, novel patterns, logic-heavy implementation, independent second opinions*

| Model | Strengths |
|-------|-----------|
| `mistral-large-3:675b-cloud` | Architecture, complex logic, design review — treat as near-Opus; reserve for load-bearing decisions |
| `kimi-k2.6:cloud` | Reasoning, long context, cross-file analysis |
| `deepseek-v4-pro:cloud` | Coding, SQL, data engineering patterns, structured output |
| `devstral-2:123b-cloud` | Code generation, software implementation — Mistral's code-focused model |

### Tier 2 — Strong Coding
*Use for: pattern application once established, solid implementation tasks*

| Model | Strengths |
|-------|-----------|
| `qwen3-coder-next:cloud` | SQL, dbt patterns — purpose-built coder |
| `nemotron-3-super:cloud` | Reasoning + coding |
| `gpt-oss:120b-cloud` | General coding, all-rounder |
| `deepseek-v4-flash:cloud` | Speed-optimized V4 — mechanical coding tasks |

### Tier 3 — Fast / Cheap
*Use for: formulaic output, high-volume templated tasks, documentation, YAML*

| Model | Strengths |
|-------|-----------|
| `gemini-3-flash-preview:cloud` | Fast, reliable, strong instruction-following — YAML, docs, templated output |
| `qwen3.5:cloud` | General purpose, fast |
| `gemma4:31b-cloud` | Lightweight — simplest mechanical tasks |
| `glm-5.1:cloud` | General, light workloads |
| `glm-5:cloud` | General, light workloads |

### Special Purpose
*Use for specific task types regardless of phase*

| Model | Use Case |
|-------|----------|
| `qwen3-vl:235b-cloud` | Multimodal — review Snowflake query plan screenshots, validate dbt lineage graphs, read architecture diagrams |
| `kimi-k2.5:cloud` | Long-context tasks — reading full spec + codebase together, cross-file analysis |
| `mistral-large-3:675b-cloud` | Independent second opinion — use when you want a non-Anthropic perspective on a design decision |

---

## Routing Decision Tree

```
Is this a project-wide or context-heavy decision?
  YES → Claude Code
  NO  ↓

Is this a new pattern appearing for the first time?
  YES → Claude Code (or OpenCode + Tier 1 if pattern is well-known)
  NO  ↓

Is this logic-heavy implementation of an established pattern?
  YES → OpenCode + Tier 2
  NO  ↓

Is this formulaic, templated, or high-volume?
  YES → OpenCode + Tier 3
  NO  → OpenCode + Tier 1 (when in doubt, go up a tier)
```

---

## Task Routing Reference

### Design & Architecture
| Task | Tool | Model |
|------|------|-------|
| Phase planning, spec review | Claude Code | Sonnet |
| Architecture decisions | Claude Code | Sonnet |
| State machine design | Claude Code | Sonnet |
| Security review (secrets, RBAC, CI) | Claude Code | Sonnet |
| Independent second opinion on design | OpenCode | `mistral-large-3:675b` |
| Long-context cross-file analysis | OpenCode | `kimi-k2.5` or `kimi-k2.6` |

### Infrastructure & Configuration
| Task | Tool | Model |
|------|------|-------|
| Snowflake RBAC setup SQL | Claude Code | Sonnet |
| GitHub Actions CI/CD YAML | Claude Code | Sonnet |
| `.devcontainer/devcontainer.json` | OpenCode | `devstral-2` |
| Docker Compose additions | OpenCode | `deepseek-v4-flash` |
| `.pre-commit-config.yaml` | OpenCode | `gemini-3-flash-preview` |
| `.gitignore`, `.env.example` | OpenCode | `gemini-3-flash-preview` |
| PR template, README sections | OpenCode | `qwen3.5` |

### Simulator
| Task | Tool | Model |
|------|------|-------|
| State machine design review | Claude Code | Sonnet |
| `simulator.py` first draft | OpenCode | `devstral-2` |
| `state_machine.py` implementation | OpenCode | `deepseek-v4-pro` |
| `schema.sql` DDL (8 tables) | OpenCode | `qwen3-coder-next` |
| `requirements.txt` | OpenCode | `gemini-3-flash-preview` |

### dbt — Staging Layer
| Task | Tool | Model |
|------|------|-------|
| First staging model (`stg_retail__orders`) | Claude Code | Sonnet |
| Staging models 2–8 | OpenCode | `qwen3-coder-next` |
| `sources.yml` + freshness thresholds | OpenCode | `gemini-3-flash-preview` |
| `profiles.yml` structure | Claude Code | Sonnet |

### dbt — Intermediate Layer
| Task | Tool | Model |
|------|------|-------|
| First intermediate model (`int_orders_enriched`) | Claude Code | Sonnet |
| Remaining intermediate models | OpenCode | `devstral-2` |

### dbt — Marts Layer
| Task | Tool | Model |
|------|------|-------|
| Incremental model (`fct_inventory_daily`) | Claude Code | Sonnet |
| SCD snapshot models | Claude Code | Sonnet |
| Remaining mart models | OpenCode | `devstral-2` |
| `dim_date` calendar dimension | OpenCode | `qwen3-coder-next` |

### dbt — Quality & Documentation
| Task | Tool | Model |
|------|------|-------|
| Custom test SQL | Claude Code | Sonnet |
| Generic test YAML (`schema.yml`) | OpenCode | `gemini-3-flash-preview` |
| Column-level descriptions (bulk) | OpenCode | `gemini-3-flash-preview` |
| Macros (`generate_schema_name`, etc.) | Claude Code | Sonnet |
| Exposures YAML | OpenCode | `qwen3.5` |

### CDC Pipeline
| Task | Tool | Model |
|------|------|-------|
| Debezium connector config design | Claude Code | Sonnet |
| Kafka consumer implementation | OpenCode | `deepseek-v4-pro` |
| MERGE/upsert Snowflake logic | Claude Code | Sonnet |
| Docker Compose CDC services | OpenCode | `deepseek-v4-flash` |

### Airflow
| Task | Tool | Model |
|------|------|-------|
| Cosmos DbtTaskGroup pattern (first time) | Claude Code | Sonnet |
| DAG operator implementations | OpenCode | `devstral-2` |
| DAG boilerplate, connections config | OpenCode | `deepseek-v4-flash` |

### Validation & Review
| Task | Tool | Model |
|------|------|-------|
| PR review before merge | Claude Code | `/code-review` skill |
| Deliverable verification | Claude Code | `/verify` skill |
| Snowflake query plan review | OpenCode | `qwen3-vl:235b` |
| dbt lineage graph review | OpenCode | `qwen3-vl:235b` |
| Debugging failures | Claude Code | Sonnet |

---

## Per-Phase Summary

| Phase | Primary Tool | Primary Model(s) | Notes |
|-------|-------------|-----------------|-------|
| 0 — GitHub Setup | Claude Code + OpenCode | Sonnet / `gemini-3-flash` | Claude Code for CI/CD design; OpenCode for boilerplate files |
| 1 — Simulator | OpenCode (design via Claude Code) | `devstral-2`, `deepseek-v4-pro` | Claude Code locks design; OpenCode implements |
| 2 — Snowflake + dbt Staging | Claude Code + OpenCode | Sonnet / `qwen3-coder-next` | Claude Code for first model + RBAC; OpenCode for remaining staging |
| 3 — Full dbt + CI/CD | Claude Code + OpenCode | Sonnet / `devstral-2` / `gemini-3-flash` | Claude Code for new patterns; OpenCode scales the rest |
| 4 — CDC | Claude Code + OpenCode | Sonnet / `deepseek-v4-pro` | Claude Code for design + MERGE logic; OpenCode for consumer |
| 5 — Airflow | Claude Code + OpenCode | Sonnet / `devstral-2` | Claude Code for Cosmos pattern; OpenCode for DAG body |
| 6 — Polish | OpenCode | `qwen3-vl:235b` / `qwen3.5` | Mostly docs + visual review; Claude Code for runbook |

---

## Cost Guidance

- **Reserve `mistral-large-3:675b`** for genuinely load-bearing decisions where you want a second opinion that isn't Claude. At 675B it's the most expensive OpenCode option.
- **`devstral-2` and `deepseek-v4-pro`** are the workhorses for implementation — high quality, reasonable cost.
- **`gemini-3-flash-preview`** is the default for anything templated or formulaic — fast and cheap.
- **`qwen3-vl:235b`** is a one-of-a-kind capability (multimodal) — use it specifically for visual validation tasks, not as a general coder.
- When uncertain which model to use, default up one tier rather than down.

---

## Agent Roster

Full definitions in `.agents/`. Summary:

| Agent | Primary Harness | Primary Model | Backup Model | Owns |
|-------|----------------|---------------|-------------|------|
| Architect | Claude Code | claude-sonnet-4-6 | `mistral-large-3:675b` | SPEC.md, DECISIONS.md, design decisions |
| Data Modeler | OpenCode | `devstral-2:123b` | `deepseek-v4-pro` | `retail_analytics/` — all dbt artifacts |
| Platform Engineer | OpenCode | `deepseek-v4-pro` | `devstral-2:123b` | Docker Compose, Postgres schema, simulator infra |
| Pipeline Engineer | OpenCode | `deepseek-v4-pro` | `kimi-k2.6` | CDC consumer, bulk load, Snowflake MERGE logic |
| CI/CD Engineer | Claude Code | claude-sonnet-4-6 | `deepseek-v4-pro` | `.github/workflows/`, pre-commit, branch protection |
| Reviewer | Claude Code | `/code-review` skill | `mistral-large-3:675b` | PR gate, deliverable verification |
| Scribe | OpenCode | `gemini-3-flash-preview` | `qwen3.5` | README, runbook, column docs, PR descriptions |

<!-- roster:architect -->

> **Auto-sync note (2026-06-02):** Agent `architect` was created. Update the Agent Roster table above manually or run the Architect agent to compose the full entry.

<!-- roster:sync-test -->

> **Auto-sync note (2026-06-02):** Agent `sync-test` was created. Update the Agent Roster table above manually or run the Architect agent to compose the full entry.

<!-- roster:platform-engineer -->

> **Auto-sync note (2026-06-02):** Agent `platform-engineer` was created. Update the Agent Roster table above manually or run the Architect agent to compose the full entry.

## Adding a New Agent — Checklist

When a new agent role is created, complete all four steps before the agent is considered done:

1. **`.agents/<role>.md`** — Full definition: role, harness config, cold start sequence, behavioral rules, handoff protocol. Use `_template.md` as the base.
2. **`.opencode/prompts/<role>.md`** — Self-contained OpenCode system prompt. Condense the agent definition + embed any skills this agent uses as inline behavioral instructions.
3. **`.opencode/config.json`** — Add profile entry with primary OpenCode model and prompt path.
4. **`AI_WORKFLOW.md` Agent Roster table** — Add a row with agent name, harnesses, models, and ownership summary.

---

## Adding a New Skill — Checklist

When a new skill is created (via `skill-creator`), complete all three steps:

1. **Build and validate the skill** using `skill-creator` — SKILL.md in the skills directory, evals pass.
2. **Embed the skill instructions** into the OpenCode prompt(s) of any agent that uses it. Skills are Claude Code-only; in OpenCode the same behavior must be expressed as inline behavioral instructions in the system prompt.
3. **Update the Agent Roster table** in this file to note which agents have the skill available in which harness.

---

## Anthropic Outage Procedure

When Claude Code / Anthropic is unavailable:

1. Open OpenCode
2. For the **Architect** role: set model to `mistral-large-3:675b-cloud`
3. Paste `.agents/architect.md` as the system prompt
4. In the first message, paste the cold start sequence:
   > "Read CLAUDE.md, SPEC.md, DECISIONS.md, and AI_WORKFLOW.md in that order. Then tell me the current phase, last completed deliverable, and next action."
5. Proceed — all decisions made during the backup session must be recorded in `DECISIONS.md` before the session ends
6. On return to Claude Code: Claude Code will re-read `CLAUDE.md` session notes and `DECISIONS.md` to reconstruct context

**Key principle:** The project files are the memory. Any model that reads `SPEC.md` + `DECISIONS.md` + `CLAUDE.md` has everything it needs to continue.

---

## Revision Log

| Date | Change |
|------|--------|
| 2026-06-02 | Initial version |
