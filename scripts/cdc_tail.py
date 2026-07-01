"""Live CDC tail — watch Debezium change events flow through Kafka in real
time, entirely within Docker (Postgres -> Debezium -> Kafka -> here), with no
Snowflake consumer needed. Built for Phase 4b so the CDC flow is directly
observable before Phase 4c's Snowflake MERGE consumer exists.

Run this in one terminal, and the simulator's stream mode in another:
    python scripts/cdc_tail.py
    SIMULATOR_DB_TYPE=postgres DATABASE_URL=... python -m simulator.main --stream

By default only shows events from the moment you start it (a fresh consumer
group each run). Pass --replay to see the full topic history from the beginning
instead, using a fixed group ID.

Ctrl-C to stop.
"""

import argparse
import signal
import sys
import uuid
from datetime import datetime
from typing import Any

from confluent_kafka import Consumer
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer
from confluent_kafka.serialization import MessageField, SerializationContext

BOOTSTRAP_SERVERS = "localhost:29092"
SCHEMA_REGISTRY_URL = "http://localhost:8081"
TOPICS = ["retail.public.orders", "retail.public.order_items", "retail.public.payments"]

_OP_LABELS = {"c": "CREATE", "u": "UPDATE", "d": "DELETE", "r": "SNAPSHOT"}

# Avro primitive/logical type names that show up as the wrapper key of a
# nullable-field union, e.g. {"boolean": false} for a nullable BOOLEAN column.
_AVRO_PRIMITIVE_NAMES = {
    "null", "boolean", "int", "long", "float", "double", "string", "bytes",
}


def _simplify(value: Any) -> Any:  # noqa: ANN401
    """Unwrap Avro union-of-named-type wrappers into plain values.

    The Avro deserializer represents a union field (nullable columns, or the
    before/after row itself, which is a union of null and a named Record) as a
    single-key dict: {"boolean": False} or {"retail.public.orders.Value": {...}}.
    Recursively unwrap anything that looks like one of those wrappers so the
    printed output reads as plain JSON instead of exposing the union encoding.
    """
    if isinstance(value, dict):
        if len(value) == 1:
            (only_key, only_val), = value.items()
            looks_like_union_wrapper = (
                "." in only_key or only_key in _AVRO_PRIMITIVE_NAMES
            )
            if looks_like_union_wrapper:
                return _simplify(only_val)
        return {k: _simplify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_simplify(v) for v in value]
    return value


def _diff(before: dict | None, after: dict | None) -> dict[str, tuple[Any, Any]]:
    """Return {field: (old, new)} for fields that changed between before/after."""
    if before is None or after is None:
        return {}
    return {
        key: (before.get(key), new_val)
        for key, new_val in after.items()
        if before.get(key) != new_val
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Live-tail Debezium CDC events")
    parser.add_argument(
        "--replay", action="store_true",
        help="Replay full topic history from the beginning (fixed group ID)",
    )
    args = parser.parse_args()

    # Python fully buffers stdout when it isn't a TTY (e.g. piped to `tee` or
    # redirected to a file) — without this, a "live" tail tool would only show
    # output in delayed bursts whenever the buffer happens to fill.
    sys.stdout.reconfigure(line_buffering=True)

    registry = SchemaRegistryClient({"url": SCHEMA_REGISTRY_URL})
    # One AvroDeserializer handles every subscribed topic — it resolves the
    # correct schema per message from the schema ID embedded in the wire format,
    # it doesn't need to be told the schema up front.
    key_deserializer = AvroDeserializer(registry)
    value_deserializer = AvroDeserializer(registry)

    # A fresh, unique group ID every run — this is a "watch what happens from
    # now" tool, not a durable consumer that should resume where it left off.
    # A fixed group ID caused two real problems during development: rerunning
    # the tool replayed the entire backlog every time (auto.offset.reset:
    # earliest), and rapid restarts under the same group ID made Kafka wait out
    # the previous session before rebalancing partitions to the new one — the
    # tool would sit silently for up to the broker's session timeout with no
    # visible error. --replay opts back into a fixed group + earliest if you
    # want to see the full history instead.
    group_id = "cdc-tail-replay" if args.replay else f"cdc-tail-{uuid.uuid4().hex[:8]}"
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP_SERVERS,
        "group.id": group_id,
        "auto.offset.reset": "earliest" if args.replay else "latest",
    })
    consumer.subscribe(TOPICS)

    print(f"Tailing {', '.join(TOPICS)} — Ctrl-C to stop\n")

    def _stop(*_args: object) -> None:
        consumer.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _stop)

    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"! consumer error: {msg.error()}", file=sys.stderr)
            continue

        table = msg.topic().rsplit(".", 1)[-1]
        ts = datetime.now().strftime("%H:%M:%S")
        key_ctx = SerializationContext(msg.topic(), MessageField.KEY)
        key = _simplify(key_deserializer(msg.key(), key_ctx))

        value = value_deserializer(
            msg.value(), SerializationContext(msg.topic(), MessageField.VALUE)
        )
        if value is None:
            # Debezium tombstone (paired with a delete) — no value payload.
            print(f"[{ts}] {table:<12} TOMBSTONE key={key}")
            continue

        op = value.get("op")
        label = _OP_LABELS.get(op, op)
        before = _simplify(value.get("before"))
        after = _simplify(value.get("after"))

        if op in ("c", "r"):
            print(f"[{ts}] {table:<12} {label:<8} key={key} -> {after}")
        elif op == "u":
            changed = _diff(before, after)
            changes = ", ".join(f"{k}: {o!r} -> {n!r}" for k, (o, n) in changed.items())
            summary = changes or "(no diff)"
            print(f"[{ts}] {table:<12} {label:<8} key={key} changed: {summary}")
        elif op == "d":
            print(f"[{ts}] {table:<12} {label:<8} key={key} -> deleted")
        else:
            print(f"[{ts}] {table:<12} op={op} key={key} value={after}")


if __name__ == "__main__":
    main()
