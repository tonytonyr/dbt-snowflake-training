"""Register the Debezium Postgres source connector against the live Kafka
Connect worker (Phase 4b).

The checked-in connector config template (docker/connectors/*.json) commits no
secrets — it holds ${VAR} placeholders substituted from .env at registration
time, the same pattern docker-compose.yml itself uses via its own ${VAR}
resolution.

Usage:
    python scripts/register_debezium_connector.py
    python scripts/register_debezium_connector.py --delete   # tear down
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "docker" / "connectors" / "retail-postgres-source.json"
CONNECT_URL = "http://localhost:8083"


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        env[key.strip()] = value.strip()
    return env


def _substitute(template: str, env: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in env:
            raise KeyError(f"{key} not found in .env — cannot register connector")
        return env[key]

    return re.sub(r"\$\{(\w+)\}", repl, template)


def register() -> None:
    env = _load_env(REPO_ROOT / ".env")
    config = json.loads(_substitute(TEMPLATE_PATH.read_text(), env))
    name = config["name"]

    body = json.dumps(config).encode()
    req = urllib.request.Request(
        f"{CONNECT_URL}/connectors",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Registered '{name}': HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        print(f"Failed to register '{name}' ({exc.code}): {detail}", file=sys.stderr)
        sys.exit(1)


def delete() -> None:
    # "name" is a plain literal in the template (no ${VAR} placeholder), so no
    # env substitution is needed just to read it.
    name = json.loads(TEMPLATE_PATH.read_text())["name"]
    req = urllib.request.Request(f"{CONNECT_URL}/connectors/{name}", method="DELETE")
    try:
        urllib.request.urlopen(req)
        print(f"Deleted connector '{name}'")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        print(f"Failed to delete '{name}' ({exc.code}): {detail}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register/delete the Debezium connector"
    )
    parser.add_argument(
        "--delete", action="store_true", help="Delete the connector instead"
    )
    args = parser.parse_args()
    delete() if args.delete else register()


if __name__ == "__main__":
    main()
