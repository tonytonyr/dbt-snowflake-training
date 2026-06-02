"""
Agent/Skill sync script — keeps Claude Code and OpenCode in sync.

Directions:
  --from-agents   : .agents/*.md changed → update .opencode/prompts/ + config.json
  --from-opencode : .opencode/prompts/*.md changed → update .agents/ + config.json
  --check         : report what is out of sync without writing anything
  --file <path>   : only process the specific file that changed (used by hooks)

Run automatically via Claude Code and OpenCode hooks, or manually:
  python scripts/sync_agents.py --check
  python scripts/sync_agents.py --from-agents
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent.parent
AGENTS_DIR = ROOT / ".agents"
OPENCODE_PROMPTS_DIR = ROOT / ".opencode" / "prompts"
OPENCODE_CONFIG = ROOT / ".opencode" / "config.json"
AI_WORKFLOW = ROOT / "AI_WORKFLOW.md"

SKIP_FILES = {"_template.md"}

# Maps role slug to primary OpenCode model (used when creating new entries)
DEFAULT_MODELS = {
    "architect": "mistral-large-3:675b-cloud",
    "data-modeler": "devstral-2:123b-cloud",
    "platform-engineer": "deepseek-v4-pro:cloud",
    "pipeline-engineer": "deepseek-v4-pro:cloud",
    "cicd-engineer": "deepseek-v4-pro:cloud",
    "reviewer": "mistral-large-3:675b-cloud",
    "scribe": "gemini-3-flash-preview:cloud",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def role_from_path(path: Path) -> str:
    return path.stem  # filename without extension


def load_opencode_config() -> dict:
    if OPENCODE_CONFIG.exists():
        return json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    return {"profiles": {}}


def save_opencode_config(config: dict) -> None:
    OPENCODE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OPENCODE_CONFIG.write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


def register_profile(role: str) -> bool:
    """Add profile entry to config.json if missing. Returns True if changed."""
    config = load_opencode_config()
    profiles = config.setdefault("profiles", {})
    if role not in profiles:
        model = DEFAULT_MODELS.get(role, "deepseek-v4-pro:cloud")
        profiles[role] = {
            "model": model,
            "system": f".opencode/prompts/{role}.md",
        }
        save_opencode_config(config)
        return True
    return False


def deregister_profile(role: str) -> bool:
    """Remove profile entry if the prompt file no longer exists."""
    config = load_opencode_config()
    profiles = config.get("profiles", {})
    if role in profiles:
        del profiles[role]
        save_opencode_config(config)
        return True
    return False


def skeleton_opencode_prompt(role: str, agent_content: str) -> str:
    """
    Generate a skeleton OpenCode prompt from an agent definition.
    Copies the core sections; marks skill embedding with a TODO.
    The AI hook will fill in the full composed version — this is a
    structural placeholder so config.json and the file exist immediately.
    """
    lines = [
        f"# {role.replace('-', ' ').title()} — System Prompt",
        "",
        "> AUTO-GENERATED SKELETON — review and expand before use.",
        "> Run: python scripts/sync_agents.py --from-agents",
        "> Or let the Claude Code hook compose the full version.",
        "",
        "---",
        "",
        "## Project Context",
        "",
        "dbt-snowflake-training project. Full spec in `SPEC.md`.",
        "",
        "---",
        "",
        "## Cold Start — Read These Files First",
        "",
        "1. `DECISIONS.md`",
        "2. `SPEC.md`",
        "3. `CLAUDE.md` (if exists)",
        "",
        "---",
        "",
        "## Role (from .agents/" + role + ".md)",
        "",
        "<!-- Content extracted from agent definition below -->",
        "",
    ]

    # Extract the Owns/Does not own block if present
    owns_match = re.search(
        r"\*\*Owns:\*\*.*?\n(.*?)(?=\n##|\Z)", agent_content, re.DOTALL
    )
    if owns_match:
        lines.append(agent_content[owns_match.start():owns_match.end()].strip())
        lines.append("")

    # Extract Behavioral Rules section
    rules_match = re.search(
        r"## Behavioral Rules\n(.*?)(?=\n##|\Z)", agent_content, re.DOTALL
    )
    if rules_match:
        lines.append("## Behavioral Rules")
        lines.append("")
        lines.append(rules_match.group(1).strip())
        lines.append("")

    lines += [
        "---",
        "",
        "## Skills (embed inline below)",
        "",
        "<!-- TODO: embed skill instructions for any skills this agent uses -->",
        "<!-- See .agents/" + role + ".md for the Claude Code skill invocations -->",
        "",
        "---",
        "",
        f"## Backup Model Note",
        "",
        f"See `.agents/{role}.md` for primary/backup model assignments.",
        "",
    ]

    return "\n".join(lines)


def skeleton_agent_definition(role: str, prompt_content: str) -> str:
    """
    Generate a skeleton .agents/ definition from an OpenCode prompt.
    Marks sections that need expansion for Claude Code-specific fields.
    """
    lines = [
        f"# Agent: {role.replace('-', ' ').title()}",
        "",
        "> AUTO-GENERATED SKELETON from .opencode/prompts/" + role + ".md",
        "> Expand with Claude Code-specific fields:",
        ">   - Harness Configuration table",
        ">   - Cold Start Sequence (Claude Code format)",
        ">   - Handoff Protocol",
        ">   - OpenCode Prompt section",
        "",
        "## Identity",
        "**Role:** [extracted from OpenCode prompt — update here]",
        "**Owns:** [update]",
        "**Does not own:** [update]",
        "",
        "## Harness Configuration",
        "",
        "| | Primary | Backup |",
        "|-|---------|--------|",
        "| **Harness** | [Claude Code or OpenCode] | [OpenCode] |",
        "| **Model** | [model] | [model] |",
        "| **When** | Normal operation | [condition] |",
        "",
        "## Cold Start Sequence",
        "",
        "1. `CLAUDE.md`",
        "2. `SPEC.md`",
        "3. `DECISIONS.md`",
        "4. `AI_WORKFLOW.md`",
        "",
        "## Behavioral Rules",
        "",
    ]

    # Extract behavioral rules from the prompt
    rules_match = re.search(
        r"## Behavioral Rules\n(.*?)(?=\n##|---|\Z)", prompt_content, re.DOTALL
    )
    if rules_match:
        lines.append(rules_match.group(1).strip())
    else:
        lines.append("[Extract from .opencode/prompts/" + role + ".md]")

    lines += [
        "",
        "## Handoff Protocol",
        "",
        "[Define handoff notes format for CLAUDE.md session notes]",
        "",
        "---",
        "",
        "## OpenCode Prompt (Required)",
        "",
        f"Corresponding prompt: `.opencode/prompts/{role}.md`",
        f"Config entry: `.opencode/config.json` profiles.{role}",
        "",
    ]

    return "\n".join(lines)


def update_ai_workflow_roster(role: str, action: str = "add") -> bool:
    """
    Add or note a role in the Agent Roster table in AI_WORKFLOW.md.
    Appends a note rather than editing the table (safer for auto-editing).
    Returns True if file was changed.
    """
    if not AI_WORKFLOW.exists():
        return False

    content = AI_WORKFLOW.read_text(encoding="utf-8")
    marker = f"<!-- roster:{role} -->"

    if action == "add" and marker not in content:
        note = (
            f"\n> **Auto-sync note ({datetime.now().strftime('%Y-%m-%d')}):** "
            f"Agent `{role}` was created. Update the Agent Roster table above manually "
            f"or run the Architect agent to compose the full entry.\n"
        )
        # Append note after the roster table section
        if "## Agent Roster" in content:
            insert_after = content.index("## Agent Roster")
            next_section = content.find("\n## ", insert_after + 1)
            if next_section == -1:
                content += f"\n{marker}\n{note}"
            else:
                content = content[:next_section] + f"\n{marker}\n{note}" + content[next_section:]
            AI_WORKFLOW.write_text(content, encoding="utf-8")
            return True

    return False


# ---------------------------------------------------------------------------
# Core sync functions
# ---------------------------------------------------------------------------

def sync_agent_to_opencode(agent_file: Path, verbose: bool = True) -> dict:
    """
    An agent definition changed → ensure OpenCode prompt and config are current.
    Returns a status dict.
    """
    role = role_from_path(agent_file)
    result = {"role": role, "actions": [], "needs_content_sync": False}

    if not agent_file.exists():
        # Agent deleted — clean up OpenCode side
        prompt_file = OPENCODE_PROMPTS_DIR / f"{role}.md"
        if prompt_file.exists():
            prompt_file.unlink()
            result["actions"].append(f"Deleted .opencode/prompts/{role}.md")
        if deregister_profile(role):
            result["actions"].append(f"Removed profile '{role}' from config.json")
        return result

    OPENCODE_PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    agent_content = agent_file.read_text(encoding="utf-8")
    prompt_file = OPENCODE_PROMPTS_DIR / f"{role}.md"

    if not prompt_file.exists():
        # New agent — create skeleton prompt
        skeleton = skeleton_opencode_prompt(role, agent_content)
        prompt_file.write_text(skeleton, encoding="utf-8")
        result["actions"].append(f"Created skeleton .opencode/prompts/{role}.md")
        result["needs_content_sync"] = True

    if register_profile(role):
        result["actions"].append(f"Added profile '{role}' to .opencode/config.json")

    update_ai_workflow_roster(role, "add")

    # Check if prompt is a skeleton and flag for content sync
    prompt_content = prompt_file.read_text(encoding="utf-8")
    if "AUTO-GENERATED SKELETON" in prompt_content or "TODO: embed skill" in prompt_content:
        result["needs_content_sync"] = True
        result["actions"].append(
            f"NOTICE: .opencode/prompts/{role}.md needs content sync — "
            f"ask the Architect agent to compose the full version from .agents/{role}.md"
        )

    if verbose:
        for action in result["actions"]:
            print(action)

    return result


def sync_opencode_to_agent(prompt_file: Path, verbose: bool = True) -> dict:
    """
    An OpenCode prompt changed → ensure .agents/ definition exists.
    Returns a status dict.
    """
    role = role_from_path(prompt_file)
    result = {"role": role, "actions": [], "needs_content_sync": False}

    if not prompt_file.exists():
        # Prompt deleted — warn but don't auto-delete the agent definition
        result["actions"].append(
            f"WARNING: .opencode/prompts/{role}.md was deleted. "
            f"Remove .agents/{role}.md manually if this agent is being retired, "
            f"then run: python scripts/sync_agents.py --from-agents"
        )
        if verbose:
            for action in result["actions"]:
                print(action)
        return result

    prompt_content = prompt_file.read_text(encoding="utf-8")
    agent_file = AGENTS_DIR / f"{role}.md"

    if not agent_file.exists():
        # New prompt created in OpenCode — create skeleton agent definition
        skeleton = skeleton_agent_definition(role, prompt_content)
        agent_file.write_text(skeleton, encoding="utf-8")
        result["actions"].append(f"Created skeleton .agents/{role}.md")
        result["needs_content_sync"] = True
        result["actions"].append(
            f"NOTICE: .agents/{role}.md is a skeleton — "
            f"ask the Architect agent (Claude Code) to expand it from "
            f".opencode/prompts/{role}.md"
        )

    if register_profile(role):
        result["actions"].append(f"Added profile '{role}' to .opencode/config.json")

    update_ai_workflow_roster(role, "add")

    if verbose:
        for action in result["actions"]:
            print(action)

    return result


def check_sync() -> list[dict]:
    """
    Report what is out of sync without writing anything.
    Returns list of issues.
    """
    issues = []
    config = load_opencode_config()
    registered = set(config.get("profiles", {}).keys())

    # Check every agent has an OpenCode prompt
    for agent_file in AGENTS_DIR.glob("*.md"):
        if agent_file.name in SKIP_FILES:
            continue
        role = role_from_path(agent_file)
        prompt_file = OPENCODE_PROMPTS_DIR / f"{role}.md"

        if not prompt_file.exists():
            issues.append({"type": "missing_prompt", "role": role,
                           "message": f"No .opencode/prompts/{role}.md for .agents/{role}.md"})
        if role not in registered:
            issues.append({"type": "missing_profile", "role": role,
                           "message": f"No config.json profile for role '{role}'"})
        elif prompt_file.exists():
            prompt_content = prompt_file.read_text(encoding="utf-8")
            if "AUTO-GENERATED SKELETON" in prompt_content:
                issues.append({"type": "skeleton_prompt", "role": role,
                               "message": f".opencode/prompts/{role}.md is still a skeleton — needs content sync"})

    # Check every OpenCode prompt has an agent definition
    if OPENCODE_PROMPTS_DIR.exists():
        for prompt_file in OPENCODE_PROMPTS_DIR.glob("*.md"):
            role = role_from_path(prompt_file)
            agent_file = AGENTS_DIR / f"{role}.md"
            if not agent_file.exists():
                issues.append({"type": "missing_agent", "role": role,
                               "message": f"No .agents/{role}.md for .opencode/prompts/{role}.md"})

    # Check every registered profile has a prompt file
    for role in registered:
        prompt_file = OPENCODE_PROMPTS_DIR / f"{role}.md"
        if not prompt_file.exists():
            issues.append({"type": "orphan_profile", "role": role,
                           "message": f"config.json profile '{role}' has no prompt file"})

    return issues


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sync agents between Claude Code and OpenCode")
    parser.add_argument("--from-agents", action="store_true",
                        help="Agent files changed → update OpenCode prompts + config")
    parser.add_argument("--from-opencode", action="store_true",
                        help="OpenCode prompts changed → update agent files + config")
    parser.add_argument("--check", action="store_true",
                        help="Report sync issues without writing anything")
    parser.add_argument("--file", type=str, default=None,
                        help="Only process this specific changed file (used by hooks)")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()

    verbose = not args.quiet

    if args.check:
        issues = check_sync()
        if not issues:
            print("✓ All agents and OpenCode prompts are in sync.")
        else:
            print(f"Found {len(issues)} sync issue(s):\n")
            for issue in issues:
                print(f"  [{issue['type']}] {issue['message']}")
        sys.exit(0 if not issues else 1)

    if args.from_agents:
        if args.file:
            path = Path(args.file)
            if path.parent.name == ".agents" and path.name not in SKIP_FILES:
                sync_agent_to_opencode(path, verbose=verbose)
            else:
                if verbose:
                    print(f"Skipping {path} (not in .agents/ or is a template)")
        else:
            for agent_file in AGENTS_DIR.glob("*.md"):
                if agent_file.name not in SKIP_FILES:
                    sync_agent_to_opencode(agent_file, verbose=verbose)

    elif args.from_opencode:
        if args.file:
            path = Path(args.file)
            if path.parent.name == "prompts":
                sync_opencode_to_agent(path, verbose=verbose)
        else:
            if OPENCODE_PROMPTS_DIR.exists():
                for prompt_file in OPENCODE_PROMPTS_DIR.glob("*.md"):
                    sync_opencode_to_agent(prompt_file, verbose=verbose)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
