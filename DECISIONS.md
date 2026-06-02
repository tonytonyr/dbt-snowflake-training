# Decision Log

Architectural and process decisions made during this project. Each entry is permanent — decisions are superseded, not deleted. This file is read by all agents at cold start and treated as settled context.

## How to Use This Document

- **Adding a decision:** Use the template below. Assign the next sequential ID.
- **Reopening a decision:** Do not edit the original entry. Add a new entry with status `supersedes: ADR-XXX` and explain what changed and why.
- **Referencing a decision:** Use the ID (e.g., "per ADR-003") in code comments, PR descriptions, and agent handoff notes.
- **Tagging:** Each entry carries one or more tags for filtering: `[architecture]` `[dbt]` `[infrastructure]` `[cdc]` `[cicd]` `[github]` `[modeling]` `[pipeline]` `[tooling]` `[process]`

---

## Template

```
### ADR-XXX — [Short title]
**Date:** YYYY-MM-DD
**Status:** Active | Superseded by ADR-XXX
**Tags:** [tag1] [tag2]

**Context:**
What situation or question prompted this decision.

**Decision:**
What was decided. Be specific — vague decisions are not useful.

**Alternatives Considered:**
What else was evaluated and why it was not chosen.

**Consequences:**
What this decision implies going forward — constraints it creates, work it enables.
```

---

## Decisions

### ADR-001 — Use GitHub Flow as branching strategy
**Date:** 2026-06-02
**Status:** Active
**Tags:** [github] [process]

**Context:**
Project needs a branching strategy. Options are Git Flow (feature/develop/release/hotfix branches), GitHub Flow (feature branches off main, PRs to main), and trunk-based development (direct commits to main with feature flags).

**Decision:**
GitHub Flow. Single long-lived branch (`main`, protected). All work on short-lived feature branches merged via PR. Branch naming: `<type>/<short-description>` where type is `feature`, `fix`, `chore`, or `docs`.

**Alternatives Considered:**
- Git Flow: overkill for a solo project; release branches add ceremony without value here.
- Trunk-based: no PR gate means no forced review step, which undermines the learning contract.

**Consequences:**
Every phase deliverable requires a PR. No direct commits to `main`. CI must pass before merge. This is intentional — the PR history documents the build progression for portfolio purposes.

---

### ADR-002 — Conventional Commits for commit message format
**Date:** 2026-06-02
**Status:** Active
**Tags:** [github] [process]

**Context:**
Consistent commit messages make the git log readable as a project narrative and enable automated changelog generation if needed later.

**Decision:**
[Conventional Commits](https://www.conventionalcommits.org/) standard. Format: `<type>(<scope>): <description>`. Types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.

**Alternatives Considered:**
- Free-form: no structure, harder to scan.
- Angular commit convention: same as Conventional Commits effectively — CC is the formalized version.

**Consequences:**
All agents producing commits must follow this format. The Reviewer checklist includes commit message format validation.

---

### ADR-003 — dbt Core via VS Code Dev Container as primary development environment
**Date:** 2026-06-02
**Status:** Active
**Tags:** [dbt] [infrastructure] [tooling]

**Context:**
dbt Core can be installed directly on the host (pip/virtualenv), run as a standalone Docker service, or run inside a VS Code Dev Container. The choice affects isolation, IDE integration, and how Airflow triggers dbt runs.

**Decision:**
VS Code Dev Container as the primary development mode. The same base image is reused as a Docker Compose service for Airflow-triggered runs. This gives full isolation, VSCode + dbt Power User extension support inside the container, and a single image maintained in two contexts.

**Alternatives Considered:**
- Local pip install: faster iteration but no isolation, host environment pollution risk.
- Standalone Docker service: good for automation but poor DX for interactive development.

**Consequences:**
`.devcontainer/devcontainer.json` and the Compose `dbt` service share a base image. Developers must use VS Code with the Dev Containers extension. dbt Power User extension is configured inside the container.

---

### ADR-004 — Astronomer Cosmos for Airflow + dbt integration
**Date:** 2026-06-02
**Status:** Active
**Tags:** [dbt] [infrastructure] [pipeline]

**Context:**
Airflow can trigger dbt via BashOperator (one task per `dbt run`), via the dbt Cloud API (requires dbt Cloud subscription), or via Astronomer Cosmos (parses dbt project into model-level tasks).

**Decision:**
Astronomer Cosmos. Parses the dbt project DAG into individual Airflow tasks — one per model — with automatic dependency ordering from `ref()`. Gives per-model retry, model-level observability, and native test integration.

**Alternatives Considered:**
- BashOperator: simple but coarse — a single model failure retries the entire project. Poor observability.
- dbt Cloud API: requires paid subscription and separates dbt from the local stack.

**Consequences:**
Airflow stack uses Astro Runtime (Astronomer's distribution) as the base image — Cosmos is pre-installed. DAGs use `DbtTaskGroup` or `DbtDag` rather than `BashOperator`.

---

### ADR-005 — Kafka in KRaft mode (no ZooKeeper)
**Date:** 2026-06-02
**Status:** Active
**Tags:** [infrastructure] [cdc]

**Context:**
Kafka historically required ZooKeeper for cluster coordination. KRaft mode (Kafka Raft) removes this dependency. ZooKeeper adds ~512MB RAM and a service to maintain.

**Decision:**
Kafka runs in KRaft mode. No ZooKeeper service in Docker Compose.

**Alternatives Considered:**
- Kafka + ZooKeeper: the traditional setup, still common in older job descriptions. Adds RAM and complexity with no learning benefit for this project.

**Consequences:**
Kafka configuration uses KRaft-specific settings (`KAFKA_PROCESS_ROLES`, `KAFKA_NODE_ID`, `KAFKA_CONTROLLER_QUORUM_VOTERS`). Any Kafka documentation referencing ZooKeeper configuration should be treated as outdated.

---

### ADR-006 — Postgres is the sole operational source; simulator writes only to Postgres
**Date:** 2026-06-02
**Status:** Active
**Tags:** [architecture] [pipeline] [cdc]

**Context:**
The e-commerce simulator could write directly to both Postgres and Snowflake to simplify the initial data load. However, this would bypass the CDC pipeline and produce an architecture that doesn't reflect production patterns.

**Decision:**
The simulator writes exclusively to Postgres. Snowflake receives data only through two channels: (1) the one-time bulk extract/load at the start of Phase 2, and (2) the ongoing CDC pipeline from Phase 4 onward. The simulator never touches Snowflake directly.

**Alternatives Considered:**
- Dual-write (Postgres + Snowflake): faster initial setup but architecturally misleading. CDC would be optional rather than the primary ingestion path.

**Consequences:**
Phase 2 requires an explicit bulk extract step from Postgres → Snowflake before dbt can run. The CDC pipeline (Phase 4) is the only ongoing write path to Snowflake RAW. This is the production-representative pattern.

---

### ADR-007 — E-commerce simulator as a two-mode event engine, not a static data generator
**Date:** 2026-06-02
**Status:** Active
**Tags:** [architecture] [infrastructure]

**Context:**
The original spec called for a static Python script to generate seed data. A simulator that models the order lifecycle as a state machine can operate in both accelerated historical mode (to generate the initial dataset) and streaming mode (to produce live events for CDC exercises).

**Decision:**
The simulator is a two-mode Python application: (1) accelerated historical mode that compresses N months of activity into minutes, and (2) streaming mode that runs at configurable real-time pace. The order lifecycle is modeled as an explicit state machine — invalid transitions are rejected.

**Alternatives Considered:**
- Static generator: simpler but produces frozen data. CDC exercises would require manually crafting test events rather than observing organic system behavior.
- Third-party data faker: less control over the state machine and lifecycle realism.

**Consequences:**
`simulator/state_machine.py` is a core artifact. The `accepted_values` dbt test on `orders.status` is meaningful because the simulator enforces valid transitions — a bug in the simulator would surface as a dbt test failure.

---

### ADR-008 — DataHub excluded from project scope
**Date:** 2026-06-02
**Status:** Active
**Tags:** [architecture] [tooling]

**Context:**
DataHub is an enterprise data catalog with native dbt integration. It was considered as a governance and observability layer.

**Decision:**
DataHub is excluded. It requires Elasticsearch, Neo4j (or Elasticsearch-as-graph), Kafka, GMS service, and frontend — approximately 4-6GB RAM on top of the existing stack. The learning value is thin relative to the resource cost for a single-pipeline project. dbt docs (`dbt docs serve`) covers the lineage and documentation use case.

**Alternatives Considered:**
- Include DataHub: adds governance concepts but likely exceeds available RAM when combined with Airflow.
- OpenMetadata: lighter alternative, but same judgment — insufficient learning return for a single project.

**Consequences:**
Observability is covered by dbt docs, Airflow UI (Cosmos task graph), and Snowflake query history. DataHub remains a candidate for a future dedicated governance project on more capable hardware.

---

### ADR-009 — Agent definitions are model-agnostic files in `.agents/`; harness is separate from brain
**Date:** 2026-06-02
**Status:** Active
**Tags:** [tooling] [process] [architecture]

**Context:**
The project uses two AI harnesses: Claude Code (primary) and OpenCode (implementation + backup). If agent context lives only in Claude Code's memory, the project is blocked when Anthropic is unavailable.

**Decision:**
Agent definitions are markdown files in `.agents/`. Each file contains: role, scope, harness configuration (primary + backup model), cold start sequence, behavioral rules, and handoff protocol. Claude Code loads them via `CLAUDE.md`. OpenCode loads them as system prompts. The same file runs in either harness — only the model changes.

**Alternatives Considered:**
- Context in Claude Code memory only: simpler but fragile — lost on session end, unavailable when Anthropic is down.
- Separate files per harness: duplicates content and creates drift risk.

**Consequences:**
All agents must maintain harness-agnostic language in their definitions (no "as Claude" references). Project files (`SPEC.md`, `DECISIONS.md`, `CLAUDE.md`) serve as the persistent memory that any model can cold-start from. Session notes in `CLAUDE.md` are the handoff mechanism between sessions.

---

### ADR-010 — dbt slim CI uses manifest state comparison; manifest artifact stored in GitHub Actions
**Date:** 2026-06-02
**Status:** Active
**Tags:** [cicd] [dbt]

**Context:**
dbt CI can run the full project on every PR (slow, expensive as the project grows) or run only changed models and their downstream dependents using `--select state:modified+` (fast, requires a reference manifest).

**Decision:**
dbt slim CI. The `cd.yml` workflow (merge to main) uploads `target/manifest.json` as a GitHub Actions artifact with 30-day retention. The `ci.yml` workflow (PR) downloads this artifact and uses it as the `--state` reference. If the artifact is missing, CI falls back to full build with a warning.

**Alternatives Considered:**
- Full build on every PR: simple but slow; doesn't demonstrate the slim CI pattern which is a common interview topic.
- Store manifest in S3/GCS: production practice but adds external dependency for a learning project.

**Consequences:**
The first PR after repo creation will run a full build (no manifest yet). Subsequent PRs run slim CI. The `cd.yml` manifest upload step is load-bearing — if it breaks, slim CI degrades to full build silently.

---

### ADR-012 — Every agent and skill requires an OpenCode composed prompt for harness portability
**Date:** 2026-06-02
**Status:** Active
**Tags:** [process] [tooling] [architecture]

**Context:**
Claude Code skills (`.skill` files, slash-command invocation) are proprietary to Claude Code. Agent context in Claude Code relies on `CLAUDE.md` auto-loading, which OpenCode does not support. Without a solution, every OpenCode session requires manual context setup and skills are unavailable entirely.

**Decision:**
Every agent definition in `.agents/<role>.md` must have a corresponding self-contained system prompt at `.opencode/prompts/<role>.md` and a profile entry in `.opencode/config.json`. Any skill built for Claude Code must also have its instructions embedded inline in the OpenCode prompt of every agent that uses it. This is a mandatory checklist item, not optional — codified in `_template.md` and `AI_WORKFLOW.md`.

**Alternatives Considered:**
- Manual context pasting per session: fragile, easy to forget, inconsistent across sessions.
- Separate OpenCode-only agent files: creates a duplicate maintenance surface and drift risk. The `.agents/` file remains source of truth; `.opencode/prompts/` is the derived artifact.

**Consequences:**
When any agent definition or skill changes, the corresponding OpenCode prompt must be updated in the same PR. The `_template.md` checklist enforces this. The `.opencode/config.json` profile system means switching agent roles in OpenCode is a single flag, zero manual intervention.

---

### ADR-011 — Initial data volume: 5K customers, 50K orders, 200K order items
**Date:** 2026-06-02
**Status:** Active
**Tags:** [architecture] [infrastructure]

**Context:**
The original spec called for 100K orders and 1M line items. This volume is appropriate for production load testing but adds significant time to development iteration (dbt full-refresh, initial Snowflake load).

**Decision:**
Starting volume: ~5K customers, ~1K products, ~50K orders, ~200K order items, 1 year of simulated history. This is sufficient to exercise all dbt patterns including incremental models, SCD snapshots, and the payment/returns reconciliation logic. Volume can be increased for specific exercises (e.g., demonstrating Snowflake clustering key impact).

**Alternatives Considered:**
- 1M line items: realistic scale but 5-10x longer iteration cycles during dbt development.
- 10K orders: too small to make incremental model behavior meaningful.

**Consequences:**
The simulator's accelerated mode targets this volume. If a phase exercise requires larger data (e.g., query performance profiling in Phase 6), the simulator can be re-run with higher parameters without changing the architecture.
