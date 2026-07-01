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

### ADR-014 — Replace JSONB metadata columns with explicit typed columns
**Date:** 2026-06-03
**Status:** Active
**Tags:** [architecture] [infrastructure]

**Context:**
`order_events.metadata` and `payment_events.metadata` were defined as `JSONB`
to hold flexible state transition context. In practice the fields are fully
predictable: order events carry `reason TEXT` and `retry_count INTEGER`;
payment events carry `failure_reason TEXT` and `retry_attempt INTEGER`. JSONB
is also the sole incompatibility blocking DuckDB as a lightweight local test
database (DuckDB does not support the JSONB type).

**Decision:**
Replace `metadata JSONB` with explicit typed columns in both event tables:
- `order_events`: add `reason TEXT`, `retry_count INTEGER`
- `payment_events`: add `failure_reason TEXT`, `retry_attempt INTEGER`

**Alternatives Considered:**
- Keep JSONB: correct for Postgres/Snowflake but blocks DuckDB compatibility
  and makes dbt models harder to read (requires JSON extraction syntax).
- Use `TEXT` with serialized JSON strings: portable but unqueryable without
  casting; worse than either JSONB or explicit columns.

**Consequences:**
`source_schema_spec.md`, `db.py` DDL, `simulate_order_lifecycle` event
inserts, and all related tests must be updated. dbt staging models can
reference `reason` and `failure_reason` directly as plain columns.

---

### ADR-013 — Python and SQL coding standards for simulator and dbt work
**Date:** 2026-06-02
**Status:** Active
**Tags:** [tooling] [process] [architecture]

**Context:**
The simulator (`simulator/`) is Python; the dbt layer and Postgres DDL are SQL. With a coding agent (Mistral via OpenCode) writing the implementation, standards must be explicit and machine-enforceable — vague guidance produces inconsistent code that is hard to review and teach from.

**Decision:**
- **Python formatter + linter:** Ruff (replaces Black + Flake8 in one tool). Configuration in `pyproject.toml`. Line length 88. Target Python 3.11+.
- **Type hints:** Required on all public functions and class methods. `mypy` or Ruff's type-check rules enforce this.
- **Test framework:** pytest. Tests live in `simulator/tests/`. One test file per source module.
- **SQL (Postgres):** `snake_case` identifiers, explicit column lists (no `SELECT *`), table-level FK constraints, `TIMESTAMP WITH TIME ZONE` for all timestamps. SQLFluff Postgres dialect for linting.
- **Full guide:** `docs/CODING_GUIDE.md` is the authoritative reference. All agents read it at cold start for any implementation task.
- **Pre-commit enforcement:** Ruff lint, Ruff format, and SQLFluff (Postgres) added to `.pre-commit-config.yaml`.

**Alternatives Considered:**
- Black + Flake8 separately: two tools with overlapping config, Ruff supersedes both with better performance.
- No type hints: acceptable for scripts, not for a state machine with complex transition logic that an agent will extend over multiple sessions.

**Consequences:**
All Python written by any agent must pass `ruff check` and `ruff format --check` before commit. `docs/CODING_GUIDE.md` is a mandatory cold-start read for Platform Engineer and Pipeline Engineer. The guide is written to be unambiguous for an AI coding agent — examples of correct and incorrect patterns are included.

---

### ADR-011 — Initial data volume: 5K customers, 50K orders, 200K order items
**Status:** Superseded by ADR-015
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

---

### ADR-015 — Address/customer relationship: household model; volumes as tunable config
**Date:** 2026-06-03
**Status:** Active
**Supersedes:** ADR-011
**Tags:** [architecture] [infrastructure]

**Context:**
The original spec modeled `addresses` as customer-owned rows with a `customer_id` FK and an `address_type` column (`shipping` / `billing`). The bootstrap data generator (notebook) models addresses as standalone geographic entities and customers as referencing an address — multiple customers may share one address to represent households (families at the same physical location). The two models are incompatible. Additionally, ADR-011 hardcoded volumes (5K customers, ~1K products) which the notebook already exceeds and which should be tunable without an ADR change.

**Decision:**
1. **Address ownership flipped:** `addresses` is a standalone table with no `customer_id` or `address_type`. Each customer row carries an `address_id` FK instead. Multiple customers sharing an `address_id` represents a household — no join table needed.
2. **No billing/shipping distinction:** Billing and shipping address are assumed identical. `address_type` is dropped. The `orders.shipping_address_id` column is retained as an explicit snapshot so historical orders survive future address changes.
3. **Volumes are config, not ADR:** Seed record counts (addresses, customers, products) are variables in `simulator/config.yaml`, not architectural decisions. The notebook's current defaults (150K addresses, ~255K customers, 25K products) are acceptable starting points; operators tune them without code changes.

**Alternatives Considered:**
- Keep `address_type` with only `shipping` as a valid value: adds a column with no analytical value and misleads future readers.
- `customer_addresses` many-to-many join table: correct for a full e-commerce model but over-engineered for this training project; the household pattern is fully captured by a shared FK.

**Consequences:**
`source_schema_spec.md` `customers` DDL gains `address_id FK`; `addresses` DDL loses `customer_id` and `address_type`. `db.py` bootstrap DDL and `generator.py` seed logic must be updated to match. The notebook CSVs are already in the correct shape — no regeneration needed. dbt staging models for `customers` gain a direct `address_id` join path.

---

### ADR-016 — New customer injection rate: random uniform 0–10% per order
**Date:** 2026-06-03
**Status:** Active
**Tags:** [architecture] [infrastructure]

**Context:**
The simulator needs to distinguish new customers (first-ever order) from returning customers to produce realistic order data for dbt analysis. A fixed ratio is unrealistic — real acquisition rates fluctuate. A configurable upper bound on a per-order uniform draw produces natural variability without extra state.

**Decision:**
For each simulated order, draw `rate = random.uniform(0, new_customer_rate_max)` and compare against a second `random.random()`. If `random.random() < rate`, generate and insert a new customer; otherwise select an existing one. `new_customer_rate_max` defaults to `0.10` (10%) in `simulator/config.yaml` and is operator-tunable. The effective mean new-customer rate is ~5% with high order-to-order variance.

Optionally, the rate draw may be done once per simulated day rather than per order, producing burst/quiet acquisition days rather than per-order noise. Implementation choice left to Platform Engineer.

**Alternatives Considered:**
- Fixed ratio in config: simple but produces unrealistically uniform acquisition — no good/bad acquisition days.
- Time-series model (e.g., sinusoidal campaign spikes): more realistic but requires significant additional complexity with no training payoff at this phase.

**Consequences:**
`simulator/config.yaml` gains `new_customer_rate_max: 0.10`. `generator.py` `create_new_customer` is called conditionally per order. Email uniqueness must be enforced by the DB `UNIQUE` constraint with retry on `IntegrityError` — the in-memory `seen` set from the notebook is not viable across simulator restarts.

**Future — market saturation (not in scope now):**
As `customers` count grows toward a total addressable market ceiling, `new_customer_rate_max` should decay via a sigmoid function of `current_customers / total_addressable_market`. Both values would be config. This is deferred until the base simulator is stable.

---

### ADR-017 — Inventory management excluded from simulation scope
**Date:** 2026-06-03
**Status:** Active
**Tags:** [architecture] [infrastructure]

**Context:**
The original spec included `inventory_quantity` on `products` as a static label used to trigger random "inventory_issue" stuck-order events. Inventory management (stock levels, depletion, replenishment) is not a goal of this simulation — all products are assumed infinitely available.

**Decision:**
Remove `inventory_quantity` from the `products` table. The `stuck_reason` values on orders are limited to non-inventory causes (e.g., `payment_failed`, `system_error`). No inventory table or stock-tracking logic will be built.

**Alternatives Considered:**
- Keep `inventory_quantity` as a cosmetic label with no depletion logic: adds a column that implies behavior the simulator doesn't implement, misleading for dbt analysis.

**Consequences:**
`products` DDL and the `products.csv` bootstrap data have no inventory column. The simulator never generates `inventory_issue` as a stuck reason. dbt models have no inventory dimension to analyze — intentional.

---

### ADR-018 — Customer pre-generation replaces runtime injection for organic growth
**Date:** 2026-06-04
**Status:** Active
**Supersedes:** ADR-016 (Phase B runtime injection aspect only; rate knob from ADR-016 is retired)
**Tags:** [architecture] [infrastructure]

**Context:**
The simulator bootstrap generates ~255K customers, the majority of whom have never placed an order. ADR-016 added runtime new-customer injection during stream mode to simulate organic acquisition. The realism levers spec (Lever 1) planned a Phase B to make injection household-aware with a SELECT guard before every insert. In parallel, stream mode needs to support CDC training exercises where the eligible customer pool grows over simulated time — matching how real systems acquire users gradually.

**Decision:**
Customer acquisition curve is baked into `created_at` at CSV generation time, not injected at runtime. The bootstrap notebook generates customers with `created_at` dates spread across the simulation window (past) and forward into the future (to sustain stream mode). Both historical and stream simulators filter eligible customers as `created_at <= current_sim_time` — the pool grows naturally as simulated time advances. No runtime `create_new_customer` injection is needed for organic growth; the pre-generated dormant population serves that role.

**Alternatives Considered:**
- Runtime injection (ADR-016 / Lever 1 Phase B): correct but adds complexity — SELECT cap-guard per insert, household-awareness logic, probability tuning. Pushes growth-curve logic into the hot path.
- Hybrid (pre-generate + top-up injection): adds complexity without proportional benefit at current scale.

**Consequences:**
- `simulator/generator.py` `create_new_customer` and `pick_customer` injection logic can be removed or reduced to an edge-case fallback.
- `simulator/config.yaml` `new_customer_rate_max` knob is retired.
- `samples/simulator_base_data.ipynb` must generate `created_at` using the seasonal sampler with a forward-looking window (e.g., 2 years beyond current date).
- The large dormant customer population is a training asset: churn, engagement cohort, and "signed-up but never ordered" dbt exercises are naturally present in the data.
- Lever 1 Phase B in `docs/SIMULATOR_REALISM_LEVERS.md` is superseded by this decision.

---

### ADR-019 — Simulator time compression ratio as project-wide coordination constant
**Date:** 2026-06-04
**Status:** Active
**Tags:** [architecture] [infrastructure] [cdc] [pipeline]

**Context:**
Stream mode needs to emit order lifecycle state transitions over real wall-clock time (not all-at-once at order creation) so CDC consumers see a realistic stream of INSERTs and UPDATEs. The cadence at which "daily" batch jobs run in Snowflake must stay in sync with the simulator's simulated time. Without a shared constant, the two sides drift — a "daily" dbt run firing every 24 real hours is meaningless if the simulator compresses a week into 30 minutes.

**Decision:**
A single `compression_ratio` integer lives in `simulator/config.yaml` (e.g., `compression_ratio: 60` means 1 real second = 60 simulated seconds). All time-dependent cadences are derived from it:

```
daily_interval_real_seconds  = 86400 / compression_ratio
hourly_interval_real_seconds = 3600  / compression_ratio
```

The simulator's transition queue uses this ratio to schedule lifecycle state updates (e.g., `confirmed → shipped` fires after `simulated_delay / compression_ratio` real seconds). The Snowflake-side orchestration reads the same value to schedule batch jobs at the correct real-world interval.

**Alternatives Considered:**
- Hardcoded intervals per side: simple but guarantees drift as the ratio is tuned.
- Wall-clock real-time stream with no compression: orders take days to complete lifecycle — impractical for training sessions.

**Consequences:**
- Stream mode requires a pending-transitions queue (orders placed but not yet fully resolved). This is a meaningful architectural addition to `simulator/main.py` and `generator.py`.
- At `compression_ratio: 60`, a 30-minute real session covers ~30 simulated hours — enough for 1–2 "daily" Snowflake batch cycles.
- `compression_ratio` is operator-tunable; changing it automatically rescales all derived cadences. No other config values need updating.

---

### ADR-021 — dbt Semantic Layer (MetricFlow) added as Phase 3d; Snowflake Semantic Views as integration target
**Date:** 2026-06-10
**Status:** Active
**Tags:** [dbt] [architecture] [modeling]

**Context:**
After the mart layer (Phase 3b), downstream consumers — BI tools, notebooks, LLMs — each risk computing metrics like `revenue` or `return_rate` independently, creating definitional drift across tools. The dbt Semantic Layer (powered by MetricFlow, open-sourced October 2025, Apache 2.0) addresses this by centralizing metric definitions in dbt YAML and translating queries into warehouse SQL at runtime. Concurrently, Snowflake Semantic Views (GA March 2026) are a native Snowflake database object offering the same centralization benefit without requiring the dbt CLI at query time. The `dbt_semantic_view` package (Snowflake Labs, October 2025) bridges both: define in dbt YAML, publish to native Snowflake objects.

**Decision:**
Add the dbt Semantic Layer as Phase 3d, delivered immediately after the mart layer. Scope:
1. MetricFlow time spine model in `models/marts/`
2. Three semantic model YAML files (`sem_orders`, `sem_customers`, `sem_products`) on top of the mart layer
3. Six metrics defined in `metrics/retail_metrics.yml`: `order_count`, `revenue`, `average_order_value`, `return_rate`, `cumulative_revenue`, `revenue_wow`
4. Three saved queries in `saved_queries/` as BI-ready metric packs
5. Publish to Snowflake Semantic Views via the `dbt_semantic_view` package as a comparison exercise

**Alternatives Considered:**
- Defer to a standalone future project: misses the opportunity to show semantic layer and mart layer as a natural progression — the data is already perfectly shaped for it.
- MetricFlow only, skip Snowflake Semantic Views: valid, but the Snowflake-native path is directly relevant to target employers (Snowflake GA March 2026 is very current) and adds a useful "two paths, same answer" comparison.
- Full BI tool integration (Tableau, Hex): adds value but introduces external dependencies and account setup friction. `mf query` via CLI is sufficient to demonstrate the pattern.

**Consequences:**
- `dbt_project.yml` must configure the MetricFlow time spine model.
- `packages.yml` gains `dbt-metricflow[snowflake]` and `snowflake-labs/dbt_semantic_view`.
- Project structure gains `semantic_models/`, `metrics/`, and `saved_queries/` directories under `retail_analytics/`.
- Phase 3d is gated on Phase 3b (mart models must exist before semantic models can reference them).
- CI/CD (`ci.yml`) should include `mf validate-configs` to catch metric definition regressions on PR.
- Interview narrative updated to mention MetricFlow and Snowflake Semantic Views — a meaningful differentiator for Snowflake-focused roles.

---

### ADR-020 — Snowflake Tasks as primary orchestrator for Snowflake-side batch jobs; Airflow deferred
**Date:** 2026-06-04
**Status:** Active
**Tags:** [architecture] [infrastructure] [pipeline]

**Context:**
The project needs a scheduler to trigger "daily" dbt-equivalent transformations in Snowflake in sync with the simulator's compression ratio (ADR-019). Options considered: external Python scheduler (APScheduler or sleep loop), Apache Airflow with Astronomer Cosmos (already planned in ADR-004), and Snowflake-native Tasks.

**Decision:**
Snowflake Tasks are the initial orchestrator for Snowflake-side batch jobs. Tasks run on a cron/interval schedule derived from `compression_ratio`, execute compiled dbt SQL or stored procedures directly, and require no external infrastructure. Task trees handle dependencies between transformation steps. Airflow (ADR-004) remains the target for cross-system orchestration (simulator → Snowflake) and is introduced when Phase 4 CDC pipeline work requires coordinating both sides.

Batch step logic is implemented as discrete callable units (stored procedures or standalone SQL scripts) so that wrapping them in Airflow operators later is a structural lift-and-shift, not a rewrite.

**Alternatives Considered:**
- Python sleep-loop script: simple but no visibility, no retry semantics, dies if the terminal closes.
- APScheduler in-process: cleaner than sleep-loop but still external to Snowflake; adds a Python dependency for what is fundamentally a SQL scheduling problem.
- Airflow immediately (ADR-004): correct long-term but over-engineered for Phase 1–3 where all work is Snowflake-internal.

**Consequences:**
- Phase 2–3 dbt models are compiled and their SQL registered as Snowflake Task payloads. Students observe Task run history in `INFORMATION_SCHEMA.TASK_HISTORY`.
- Airflow + Cosmos (ADR-004) is not removed from scope — it activates in Phase 4 as the cross-system coordinator. ADR-004 remains active.
- Task schedule intervals must be recomputed and Tasks recreated whenever `compression_ratio` changes. This is a known operational cost accepted for simplicity.

---

### ADR-022 — Dev target uses DuckDB (or Postgres) to avoid Snowflake costs and prod risk
**Date:** 2026-06-12
**Status:** Under Consideration
**Tags:** [architecture] [developer-experience] [cost]

**Context:**
All development in Phases 1–3 runs directly against the Snowflake trial account. This has two downsides: (1) every `dbt run` consumes Snowflake credits, and trial credits are finite — aggressive local iteration can exhaust them before Phase 4 CDC work begins; (2) an errant `dbt run --full-refresh` or schema migration in dev can overwrite tables that are also used for testing and demos, since dev and prod share the same account.

The project already has DuckDB as the simulator's local database (ADR-006 superseded by ADR-021 and the Phase 1 rewrite). dbt supports DuckDB via `dbt-duckdb` as a fully functional dev target — models, tests, snapshots, and incremental logic all work against it locally with no warehouse spin-up and zero cost.

Alternatively, a local Postgres instance (via Docker Compose) can serve as the dev target using `dbt-postgres`, which is closer to a real warehouse dialect than DuckDB but requires running a container.

**Decision:**
Not yet made. Two viable paths identified:

**Option A — DuckDB dev target:**
- Add a `dev` profile output in `profiles.yml` pointing to a local `dev.duckdb` file
- Set `DBT_TARGET=dev` locally; CI and prod continue to target Snowflake
- Pros: zero cost, zero setup, instant startup, works offline
- Cons: DuckDB SQL dialect diverges from Snowflake in a few places (e.g., `GENERATOR`, some date functions, `COPY INTO`); Snowflake-specific materializations may need dialect guards

**Option B — Postgres dev target:**
- Spin up a Postgres container in Docker Compose; add a `dev` profile output
- Pros: `dbt-postgres` is the most battle-tested dbt adapter; dialect is more standard than DuckDB
- Cons: requires Docker running locally; still diverges from Snowflake on warehouse-specific features (clustering, stages, Snowflake Tasks)

**Alternatives Considered:**
- Snowflake dev schema (current approach): simple but expensive and carries prod-bleed risk
- Separate Snowflake trial account for dev: eliminates prod-bleed risk but doesn't solve credit burn and adds credential management overhead

**Consequences (if adopted):**
- `profiles.yml` gains a `dev` output alongside the existing `prod` output; target is controlled by `DBT_TARGET` env var
- Any Snowflake-specific SQL (e.g., `TABLE(GENERATOR(...))` in `dim_date`, `metricflow_time_spine`) will need conditional dialect handling via `{{ target.type }}` guards or separate model variants
- CI continues to run against Snowflake using the `prod` profile — slim CI credit burn is acceptable; it's local iteration that's the cost concern
- This pattern (cheap local dev target + real warehouse for CI/prod) is a common real-world setup worth demonstrating

---

### ADR-023 — Iceberg + Trino lakehouse migration as stretch phase
**Date:** 2026-06-12
**Status:** Under Consideration
**Tags:** [architecture] [stretch] [lakehouse]

**Context:**
After the core project phases are complete (Phases 1–6), there is an opportunity to extend the project with a migration from Snowflake to an open lakehouse architecture using Apache Iceberg as the table format and Trino (or Spark) as the query engine. This represents a meaningful shift in the modern data stack landscape: many enterprises are moving toward open formats to avoid warehouse vendor lock-in, and the Iceberg + Trino pattern is appearing frequently in interviews at companies with large-scale data platforms (DoorDash, Instacart, Stripe, Airbnb).

The stretch phase would demonstrate the ability to run the same dbt transformation logic against a different execution engine by swapping the dbt adapter (`dbt-trino` in place of `dbt-snowflake`) while keeping the DAG and model SQL largely unchanged.

**Decision:**
Not yet made. Captured here as an explicit candidate for a stretch phase rather than an ad-hoc addition. Key questions to resolve before committing:
1. Does `dbt-trino` support all features used in this project (incremental models, snapshots, MetricFlow)?
2. What is the local infrastructure cost — Trino + a local Iceberg catalog (Nessie or a Hive metastore) adds meaningful Docker Compose complexity
3. What is the intended interview narrative — migration story, or parallel deployment?

**Proposed scope (if adopted):**
- Stand up Trino + MinIO (S3-compatible local object store) + Nessie (Iceberg catalog) via Docker Compose
- Export Snowflake marts to Parquet; register as Iceberg tables in Nessie
- Swap `profiles.yml` target to `dbt-trino`; run `dbt build` against Trino
- Demonstrate same query results from both Snowflake and Trino paths
- Document the migration story: what changed (adapter, catalog config), what didn't (model SQL, DAG, tests)

**Alternatives Considered:**
- Delta Lake + Spark: larger ecosystem but heavier local infrastructure; Spark is less relevant to the target employer set than Trino
- Databricks: directly relevant but requires a paid account; not feasible as a local-first portfolio project
- Skip entirely: the core project already demonstrates enough depth; the stretch is additive, not required

**Consequences (if adopted):**
- Added to Phase 7 (Stretch) in SPEC.md
- Does not affect Phases 1–6; can be attempted after Phase 6 portfolio polish is complete
- Iceberg/Trino familiarity is a meaningful differentiator for staff/principal DE roles at companies running open lakehouses alongside or instead of cloud warehouses

---

### ADR-024 — Avro + Schema Registry for CDC event serialization
**Date:** 2026-07-01
**Status:** Active
**Tags:** [architecture] [cdc] [infrastructure] [governance]

**Context:**
Phase 4 already introduces Kafka in KRaft mode (ADR-005) as the transport for Debezium CDC
events out of Postgres (ADR-006). Left unconfigured, Debezium's default converter serializes
change events as JSON-with-embedded-schema — verbose, and with no enforced contract between
producer and consumer. A schema changing shape on the Postgres side (a column added, renamed,
or dropped) would silently propagate to the Kafka consumer with no compatibility check.

This is a narrower concern than the data-catalog/governance question closed by ADR-008
(DataHub/OpenMetadata excluded). ADR-008 rejected those tools because they bundle a catalog,
lineage graph, and UI on top of Elasticsearch/Neo4j — multi-GB of infrastructure for thin
learning return on a single-pipeline project. Schema Registry is a different shape of tool: a
single lightweight REST service backed by a Kafka topic, with no graph store or frontend, and
it rides on Kafka infrastructure Phase 4 is standing up regardless. The learning-value/resource
tradeoff that killed ADR-008 does not apply here.

**Decision:**
Add Confluent Schema Registry to the Phase 4 Docker Compose stack. Debezium's Postgres
connector is configured with `key.converter` / `value.converter` set to
`io.confluent.connect.avro.AvroConverter` (Avro instead of the default JSON converter), pointed
at the registry. The Python CDC consumer deserializes with an Avro deserializer
(`confluent-kafka`'s `AvroDeserializer` or `fastavro`) resolving schema IDs against the
registry instead of `json.loads`. Compatibility mode is set to `BACKWARD` on the subjects for
`orders`, `order_items`, and `returns` — the three tables Debezium is already configured to
watch (SPEC.md Phase 4 step 2).

Phase 4 gets one deliberate schema-evolution exercise: add a nullable column to `orders` in
Postgres and confirm the registry accepts the new schema version under `BACKWARD`
compatibility; then attempt a breaking change (drop or retype an existing column) and observe
the registry reject the write. This is the concrete artifact that makes "schema evolution and
compatibility contracts" a defensible interview talking point rather than a name-drop.

**Alternatives Considered:**
- **Karapace** (Aiven's Apache-2.0-licensed Schema Registry, API-compatible with Confluent's):
  avoids Confluent's Community License and is marginally lighter. Confluent Schema Registry is
  chosen instead because it's the term most job descriptions and interviewers use — the
  license terms (free to use, restricted only from reselling it as a competing hosted service)
  don't affect a local training project. Karapace remains a drop-in swap if licensing becomes
  a concern later.
- **JSON Schema** instead of Avro: also supported by Schema Registry and Debezium, more
  human-readable, but larger on the wire and less standard for CDC pipelines specifically.
  Avro is Debezium's most common pairing in production and in tutorials/job descriptions.
- **Protobuf:** viable third serialization option; skipped for scope — less common in the
  Debezium ecosystem than Avro, no added teaching value for this project.
- **Stay on JSON, skip Schema Registry entirely:** zero new infrastructure, but forfeits the
  entire teaching point (schema evolution, compatibility enforcement) that motivated adding
  this in the first place — the whole reason for reconsidering data governance for this
  project (see also ADR-008).

**Consequences:**
- New `schema-registry` service in the Phase 4 Docker Compose file — adds ~150–300MB RAM on
  top of the ~1.5GB already budgeted for Phase 4 (Kafka + Debezium); see updated Infrastructure
  Stack table in SPEC.md.
- Debezium connector config (SPEC.md Phase 4 step 2) changes from the default JSON converter to
  `AvroConverter` with `schema.registry.url` set.
- The Python CDC consumer (SPEC.md Phase 4 step 3) needs an Avro deserializer dependency
  (`confluent-kafka[avro]` or `fastavro`) instead of the stdlib `json` module.
- `RAW.retail` MERGE/upsert logic in Snowflake (SPEC.md Phase 4 step 3) is unaffected — Avro
  deserialization happens consumer-side before the MERGE, not in Snowflake.
- Does not reopen ADR-008. A dedicated data catalog (OpenMetadata/DataHub) remains out of
  scope for this project; this ADR covers schema-contract enforcement on the CDC stream only,
  not lineage, glossary, or discovery tooling.
