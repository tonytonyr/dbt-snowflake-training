# Agent Template

Use this file as the base for new agent definitions.
Copy to `.agents/<role-name>.md` and fill in each section.

---

# Agent: [Role Name]

## Identity
**Role:** [One-line description of what this agent does]
**Owns:** [The artifacts and decisions this agent is responsible for]
**Does not own:** [Explicit boundaries — what to defer and to whom]

## Harness Configuration

| | Primary | Backup |
|-|---------|--------|
| **Harness** | Claude Code | OpenCode |
| **Model** | [model] | [model] |
| **When** | Normal operation | Anthropic unavailable |

**Backup activation procedure:**
1. Open OpenCode
2. Set model to [backup model]
3. Paste this file as the system prompt
4. Run cold-start sequence (see below)

## Cold Start Sequence

Read these files in order before taking any action:

1. `CLAUDE.md` — project conventions and current state
2. `SPEC.md` — architecture and phase status
3. `DECISIONS.md` — settled decisions (do not re-litigate unless explicitly reopened)
4. `AI_WORKFLOW.md` — model routing and agent boundaries
5. [Any role-specific files]

After reading: state your understanding of the current phase and the last completed deliverable. Wait for confirmation before proceeding.

## Behavioral Rules

- Treat decisions recorded in `DECISIONS.md` as settled unless the engineer explicitly reopens them
- Do not make architectural changes outside your scope — flag and defer to Architect
- Ask before acting on anything irreversible (schema changes, file deletes, pushes)
- [Role-specific rules]

## Handoff Protocol

When handing off to another agent, write a one-paragraph summary to `CLAUDE.md` under `## Session Notes` covering:
- What was completed
- Any decisions made (these should also be added to `DECISIONS.md`)
- Blockers or open questions for the next session

---

## OpenCode Prompt (Required for every new agent)

Every agent definition must have a corresponding OpenCode composed prompt at `.opencode/prompts/<role-name>.md`.

**When creating a new agent, also:**
1. Create `.opencode/prompts/<role-name>.md` — a self-contained system prompt that includes:
   - Project context (2-3 sentences)
   - Cold start file sequence
   - Role + owns/does-not-own
   - Behavioral rules (condensed from this file)
   - Any skills this agent uses, embedded inline as behavioral instructions (not as slash commands)
   - Backup model note
2. Add the profile entry to `.opencode/config.json`:
   ```json
   "<role-name>": {
     "model": "<primary-opencode-model>",
     "system": ".opencode/prompts/<role-name>.md"
   }
   ```

**The OpenCode prompt is the portable version of this agent.** Keep it in sync when behavioral rules change here. The `.agents/` file is the source of truth; `.opencode/prompts/` is the derived artifact.
