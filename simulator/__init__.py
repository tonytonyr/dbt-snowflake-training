"""E-commerce simulator package."""

from pathlib import Path
from typing import Any

import yaml


def load_config() -> dict[str, Any]:
    """Load simulator configuration from config.yaml."""
    config_path = Path(__file__).parent / "config.yaml"
    with config_path.open() as f:
        return yaml.safe_load(f)


# Re-export key symbols for cleaner imports
from simulator.db import Database as Database  # noqa: E402
from simulator.state_machine import OrderState as OrderState  # noqa: E402
from simulator.state_machine import PaymentState as PaymentState  # noqa: E402
from simulator.state_machine import StateMachine as StateMachine  # noqa: E402
