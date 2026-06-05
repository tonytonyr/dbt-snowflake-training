"""Unit tests for simulator/state_machine.py.

Tests cover:
- Deterministic transitions (apply_order_transition).
- Probabilistic transitions (attempt_order_transition, attempt_payment_transition).
- Terminal state checks.
- Edge cases (stuck orders, max retries).
"""

import logging

import pytest

from simulator.state_machine import (
    MAX_RETRIES,
    TERMINAL_ORDER_STATES,
    TERMINAL_PAYMENT_STATES,
    InvalidTransitionError,
    OrderState,
    PaymentState,
    StateMachine,
)


@pytest.fixture(autouse=True)
def disable_logging() -> None:
    """Disable debug logging during tests."""
    logging.getLogger("simulator.state_machine").setLevel(logging.WARNING)


class TestApplyOrderTransition:
    """Tests for deterministic order transitions."""

    @pytest.mark.parametrize(
        ("current_state", "event", "expected_next_state", "expected_actions"),
        [
            (OrderState.PLACED, "confirm", OrderState.CONFIRMED, ["reserve_inventory"]),
            (OrderState.PLACED, "cancel", OrderState.CANCELLED, ["release_inventory"]),
            (OrderState.CONFIRMED, "ship", OrderState.SHIPPED,
             ["generate_shipping_label"]),
            (OrderState.SHIPPED, "deliver", OrderState.DELIVERED, ["update_inventory"]),
            (OrderState.SHIPPED, "return", OrderState.RETURNED, ["process_refund"]),
        ],
    )
    def test_valid_transitions(
        self,
        current_state: OrderState,
        event: str,
        expected_next_state: OrderState,
        expected_actions: list[str],
    ) -> None:
        """Valid transitions return the correct next state and actions."""
        next_state, actions = StateMachine.apply_order_transition(current_state, event)
        assert next_state == expected_next_state
        assert actions == expected_actions

    @pytest.mark.parametrize(
        ("current_state", "event"),
        [
            (OrderState.PLACED, "ship"),  # Invalid event for state
            (OrderState.CONFIRMED, "deliver"),  # Invalid event for state
            (OrderState.RETURNED, "return"),  # Terminal state
        ],
    )
    def test_invalid_transitions(self, current_state: OrderState, event: str) -> None:
        """Invalid transitions raise InvalidTransitionError."""
        with pytest.raises(InvalidTransitionError):
            StateMachine.apply_order_transition(current_state, event)


class TestAttemptOrderTransition:
    """Tests for probabilistic order transitions."""

    @pytest.mark.parametrize(
        ("current_state", "possible_states"),
        [
            (OrderState.PLACED, [OrderState.CONFIRMED, OrderState.CANCELLED]),
            (OrderState.CONFIRMED, [OrderState.SHIPPED, OrderState.CANCELLED]),
            (OrderState.SHIPPED, [OrderState.DELIVERED, OrderState.RETURNED, None]),
            (OrderState.DELIVERED, [OrderState.RETURNED, None]),
        ],
    )
    def test_probabilistic_transitions(
        self, current_state: OrderState, possible_states: list[OrderState | None]
    ) -> None:
        """Probabilistic transitions return a valid next state or None (stuck)."""
        next_state = StateMachine.attempt_order_transition(current_state)
        assert next_state in possible_states

    def test_terminal_states_return_none(self) -> None:
        """Terminal states return None (no transition)."""
        for state in TERMINAL_ORDER_STATES:
            assert StateMachine.attempt_order_transition(state) is None


class TestAttemptPaymentTransition:
    """Tests for probabilistic payment transitions."""

    @pytest.mark.parametrize(
        ("current_state", "retry_count", "possible_states"),
        [
            (PaymentState.PENDING, 0, [PaymentState.AUTHORIZED, PaymentState.FAILED]),
            (PaymentState.AUTHORIZED, 0, [PaymentState.CAPTURED, PaymentState.FAILED]),
            (PaymentState.FAILED, 0, [PaymentState.PENDING, None]),  # 50% retry
            (PaymentState.FAILED, MAX_RETRIES, [None]),  # Terminal after max retries
            (PaymentState.CAPTURED, 0, [None]),  # terminal; refunds are order-triggered
        ],
    )
    def test_probabilistic_transitions(
        self,
        current_state: PaymentState,
        retry_count: int,
        possible_states: list[PaymentState | None],
    ) -> None:
        """Probabilistic transitions return a valid next state or None (terminal)."""
        next_state = StateMachine.attempt_payment_transition(current_state, retry_count)
        assert next_state in possible_states

    @pytest.mark.parametrize("state", TERMINAL_PAYMENT_STATES)
    def test_terminal_states_return_none(self, state: PaymentState) -> None:
        """Terminal states return None (no transition)."""
        assert StateMachine.attempt_payment_transition(state, 0) is None

    def test_failed_payment_becomes_terminal_after_max_retries(self) -> None:
        """Failed payments become terminal after MAX_RETRIES."""
        for retry_count in range(MAX_RETRIES):
            next_state = StateMachine.attempt_payment_transition(
                PaymentState.FAILED, retry_count
            )
            assert next_state in [PaymentState.PENDING, None]

        # After max retries, must be terminal
        result = StateMachine.attempt_payment_transition(
            PaymentState.FAILED, MAX_RETRIES
        )
        assert result is None


class TestTerminalStateChecks:
    """Tests for terminal state checks."""

    @pytest.mark.parametrize("state", TERMINAL_ORDER_STATES)
    def test_is_terminal_order_state(self, state: OrderState) -> None:
        """Terminal order states are correctly identified."""
        assert StateMachine.is_terminal_order_state(state)

    @pytest.mark.parametrize("state", set(OrderState) - TERMINAL_ORDER_STATES)
    def test_is_not_terminal_order_state(self, state: OrderState) -> None:
        """Non-terminal order states are correctly identified."""
        assert not StateMachine.is_terminal_order_state(state)

    @pytest.mark.parametrize(
        ("state", "retry_count", "expected"),
        [
            (PaymentState.FAILED, MAX_RETRIES, True),  # Terminal after max retries
            (PaymentState.FAILED, 0, False),  # Non-terminal (can retry)
            (PaymentState.CAPTURED, 0, True),  # Terminal
            (PaymentState.REFUNDED, 0, True),  # Terminal
            (PaymentState.PENDING, 0, False),  # Non-terminal
        ],
    )
    def test_is_terminal_payment_state(
        self, state: PaymentState, retry_count: int, expected: bool
    ) -> None:
        """Terminal payment states are correctly identified."""
        assert StateMachine.is_terminal_payment_state(state, retry_count) == expected
