"""Models valid order and payment lifecycle transitions and their probabilities.

Core logic for the e-commerce simulator state machine. Transitions are atomic
and probabilistic, aligned with docs/simulator_state_machine.md.
"""

import logging
import random
from enum import Enum

logger = logging.getLogger(__name__)


class OrderState(Enum):
    """Valid states for an order."""
    PLACED = "placed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    RETURNED = "returned"


class PaymentState(Enum):
    """Valid states for a payment."""
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


TERMINAL_ORDER_STATES = {
    OrderState.CANCELLED,
    OrderState.RETURNED,
}

TERMINAL_PAYMENT_STATES = {
    PaymentState.CAPTURED,
    PaymentState.REFUNDED,
    # PaymentState.FAILED removed to avoid breaking retry logic
}

MAX_RETRIES = 3


class InvalidTransitionError(Exception):
    """Raised when a transition is invalid for the current state."""


class StateMachine:
    """Core state transition logic for orders and payments."""

    # Transition rules: (current_state, event) -> (next_state, actions)
    _ORDER_TRANSITIONS: dict[tuple[OrderState, str], tuple[OrderState, list[str]]] = {
        (OrderState.PLACED, "confirm"): (OrderState.CONFIRMED, ["reserve_inventory"]),
        (OrderState.PLACED, "cancel"): (OrderState.CANCELLED, ["release_inventory"]),
        (OrderState.CONFIRMED, "ship"): (
            OrderState.SHIPPED, ["generate_shipping_label"]
        ),
        (OrderState.CONFIRMED, "cancel"): (OrderState.CANCELLED, ["release_inventory"]),
        (OrderState.SHIPPED, "deliver"): (OrderState.DELIVERED, ["update_inventory"]),
        (OrderState.SHIPPED, "return"): (OrderState.RETURNED, ["process_refund"]),
        (OrderState.DELIVERED, "return"): (OrderState.RETURNED, ["process_refund"]),
    }

    # Probability weights for order transitions
    _ORDER_PROBABILITIES: dict[OrderState, dict[OrderState | None, float]] = {
        OrderState.PLACED: {
            OrderState.CONFIRMED: 0.97,
            OrderState.CANCELLED: 0.03,  # 2% payment failure + 1% user cancel
        },
        OrderState.CONFIRMED: {
            OrderState.SHIPPED: 0.98,
            OrderState.CANCELLED: 0.02,  # 1% user cancel + 1% random failure
        },
        OrderState.SHIPPED: {
            OrderState.DELIVERED: 0.96,
            OrderState.RETURNED: 0.03,
            None: 0.01,  # 1% stuck (no transition)
        },
        OrderState.DELIVERED: {
            OrderState.RETURNED: 0.03,
            # None exits the lifecycle loop in compute_order_lifecycle without a
            # transition — order stays DELIVERED.  DELIVERED is intentionally not
            # in TERMINAL_ORDER_STATES so returns remain possible.
            None: 0.97,
        },
    }

    # Probability weights for payment transitions
    _PAYMENT_PROBABILITIES: dict[PaymentState, dict[PaymentState | None, float]] = {
        PaymentState.PENDING: {
            PaymentState.AUTHORIZED: 0.98,
            PaymentState.FAILED: 0.02,
        },
        PaymentState.AUTHORIZED: {
            PaymentState.CAPTURED: 0.99,
            PaymentState.FAILED: 0.01,
        },
        PaymentState.FAILED: {
            PaymentState.PENDING: 0.5,  # 50% retry chance
            None: 0.5,  # 50% terminal failure
        },
        # PaymentState.CAPTURED removed (refunds are order-triggered)
    }

    @classmethod
    def is_terminal_order_state(cls, state: OrderState) -> bool:
        """Check if an order state is terminal."""
        return state in TERMINAL_ORDER_STATES

    @classmethod
    def is_terminal_payment_state(cls, state: PaymentState, retry_count: int) -> bool:
        """Check if a payment state is terminal.

        Failed payments become terminal after MAX_RETRIES.
        """
        if state == PaymentState.FAILED and retry_count >= MAX_RETRIES:
            return True
        return state in TERMINAL_PAYMENT_STATES

    @classmethod
    def apply_order_transition(
        cls,
        current_state: OrderState,
        event: str,
    ) -> tuple[OrderState, list[str]]:
        """Apply a deterministic transition based on an event.

        Raises:
            InvalidTransitionError: If the transition is invalid.
        """
        key = (current_state, event)
        if key not in cls._ORDER_TRANSITIONS:
            raise InvalidTransitionError(
                f"Invalid transition: {current_state} + {event}"
            )
        return cls._ORDER_TRANSITIONS[key]

    @classmethod
    def attempt_order_transition(
        cls,
        current_state: OrderState,
    ) -> OrderState | None:
        """Attempt a probabilistic transition for an order.

        Returns:
            Next state or None if the order is stuck (no transition).
        """
        if current_state not in cls._ORDER_PROBABILITIES:
            return None  # Terminal or invalid state

        states = list(cls._ORDER_PROBABILITIES[current_state].keys())
        weights = list(cls._ORDER_PROBABILITIES[current_state].values())
        next_state = random.choices(states, weights=weights, k=1)[0]
        logger.debug(
            "Order transition: %s -> %s (weights: %s)",
            current_state.value,
            next_state.value if next_state else "stuck",
            weights,
        )
        return next_state

    @classmethod
    def attempt_payment_transition(
        cls,
        current_state: PaymentState,
        retry_count: int,
    ) -> PaymentState | None:
        """Attempt a probabilistic transition for a payment.

        Failed payments may retry up to MAX_RETRIES.

        Returns:
            Next state or None if the payment is stuck (no transition).
        """
        if current_state not in cls._PAYMENT_PROBABILITIES:
            return None  # Terminal or invalid state

        # Cap retries for failed payments
        if current_state == PaymentState.FAILED and retry_count >= MAX_RETRIES:
            return None  # Terminal failure

        states = list(cls._PAYMENT_PROBABILITIES[current_state].keys())
        weights = list(cls._PAYMENT_PROBABILITIES[current_state].values())
        next_state = random.choices(states, weights=weights, k=1)[0]
        logger.debug(
            "Payment transition: %s -> %s (retry_count=%d, weights: %s)",
            current_state.value,
            next_state.value if next_state else "terminal",
            retry_count,
            weights,
        )
        return next_state
