# Source Schema Specification

This document defines the SQL tables for the e-commerce source schema, aligned with the [Simulator State Machine](simulator_state_machine.md). Tables are designed to support order lifecycle, payment processing, and edge cases (e.g., stuck orders, random failures).

## Core Tables

### 1. `orders`
Tracks order state transitions and metadata.

```sql
CREATE TABLE orders (
    order_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    order_state TEXT NOT NULL,
      -- Values: placed, confirmed, cancelled, shipped, delivered, returned
    order_date TIMESTAMP WITH TIME ZONE NOT NULL,
    first_event_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    subtotal NUMERIC(12, 2) NOT NULL,
    tax NUMERIC(12, 2) NOT NULL,
    shipping_cost NUMERIC(12, 2) NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    shipping_address_id TEXT NOT NULL,
      -- Typically the customer's home address; stored explicitly so historical orders survive address changes.
    is_stuck BOOLEAN DEFAULT FALSE,
      -- Edge case: 1% of orders may fail to transition
    stuck_reason TEXT,
      -- e.g., "payment_failed", "system_error"
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (shipping_address_id) REFERENCES addresses(address_id)
    -- payment_id removed to avoid circular FK. Join via `payments.order_id`.
);
```

### 2. `payments`
Tracks payment state transitions and atomicity with orders.

```sql
CREATE TABLE payments (
    payment_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    payment_state TEXT NOT NULL,
      -- Values: pending, authorized, captured, refunded, failed
    amount NUMERIC(12, 2) NOT NULL,
    payment_method TEXT NOT NULL,
      -- e.g., "credit_card", "paypal"
    payment_date TIMESTAMP WITH TIME ZONE,
    authorization_date TIMESTAMP WITH TIME ZONE,
    capture_date TIMESTAMP WITH TIME ZONE,
    refund_date TIMESTAMP WITH TIME ZONE,
    failure_reason TEXT,
      -- e.g., "declined", "fraud_risk"
    retry_count INTEGER DEFAULT 0,
      -- Max 3 retries for failed payments. After 3 retries, `failed` becomes terminal.
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
```

### 3. `order_items`
Line items for each order.

```sql
CREATE TABLE order_items (
    order_item_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price NUMERIC(12, 2) NOT NULL,
    total_price NUMERIC(12, 2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);
```

### 4. `customers`
Customer metadata. Volume is configurable (see `simulator/config.yaml`).

```sql
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    address_id TEXT NOT NULL,
      -- Home address. Multiple customers may share one address (household model).
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    FOREIGN KEY (address_id) REFERENCES addresses(address_id)
);
```

### 5. `addresses`
Physical addresses. Standalone entities — not owned by a single customer.
Billing and shipping are assumed identical; no `address_type` column.
Volume is configurable (see `simulator/config.yaml`).

```sql
CREATE TABLE addresses (
    address_id TEXT PRIMARY KEY,
    street_address TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country TEXT NOT NULL
);
```

### 6. `products`
Product catalog (target: ~1,000 products across 4–6 categories).

```sql
CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price NUMERIC(12, 2) NOT NULL,
    cost_price NUMERIC(12, 2) NOT NULL,
    category TEXT NOT NULL
);
```

## Event Tables

### 7. `order_events`
Logs all order state transitions for auditing.

```sql
CREATE TABLE order_events (
    event_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata JSONB,
      -- e.g., {"reason": "payment_failed", "retry_count": 2}
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);
```

### 8. `payment_events`
Logs all payment state transitions for auditing.

```sql
CREATE TABLE payment_events (
    event_id TEXT PRIMARY KEY,
    payment_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata JSONB,
      -- e.g., {"failure_reason": "declined", "retry_attempt": 1}
    FOREIGN KEY (payment_id) REFERENCES payments(payment_id)
);
```

## Proposed Modifications to Source Schema

1. **`orders` Table**:
   - Added `is_stuck` and `stuck_reason` to model 1% random failures.
   - Added `order_state` (replaces generic `status`).

2. **`payments` Table**:
   - Added `retry_count` to enforce max retries (3x).
   - Added `payment_state` (replaces generic `status`).

3. **New Tables**:
   - `order_events` and `payment_events` for auditing state transitions.

4. **Edge Case Support**:
   - `metadata` (JSONB) in event tables captures failure reasons/retries.

5. **Reference Data Enhancements**:
   - **`products`**: Added `category` and `cost_price` for dbt analysis.
   - **`customers`**: Added `region` for geographic analysis.

6. **Bootstrap Mode**:
   - Schema includes seed data for products, customers, and addresses. Volumes are configurable via `simulator/config.yaml` (see ADR-015).
   - Inventory is static (not updated during simulation).

## References
- [Simulator State Machine](simulator_state_machine.md) (transition rules, probabilities).