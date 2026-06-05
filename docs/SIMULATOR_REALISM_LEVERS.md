# Simulator Realism Levers — Mini Spec

**Status:** Lever 1 complete. Levers 2 and 3 deferred post-Phase 2.  
**Prerequisite:** Current Phase 1 simulator fully functional with seasonal/skew distributions  
**Scope:** Three independent levers, each delivered as its own PR

> **ADR updates since initial spec:**
> - **ADR-018** supersedes Lever 1 Phase B (runtime injection). Customer growth curve is baked into `created_at` at CSV generation time; stream mode filters by `created_at <= current_sim_time`. Phase B runtime injection is removed from scope.
> - **ADR-019** adds a `compression_ratio` config knob that governs stream mode transition cadence. Stream mode now maintains a pending-transitions queue rather than finalizing all lifecycle events at order creation time. See [Stream Mode Architecture](#stream-mode-architecture) section below.

---

## Overview

Three additions to make generated data more realistic for lakehouse loading exercises.
All three must work in both `--historical` and `--stream` modes using the same
underlying functions — no mode-specific divergence.

---

## Lever 1 — Dynamic Customer Acquisition ✅ Complete

### Goal
Customers in the dataset should appear to join over time following demand-shaped
patterns, not all pre-exist from day one. Household members join organically
after their primary customer, with a hard cap of 9 per household.

### Approach
Reuse `_seasonal_weight()` and `_sample_order_dates()` — customer acquisition
follows the same seasonal signal as order volume (new customers sign up because
they are buying). This is architecturally honest: December spikes mint new
accounts; January slumps mean fewer sign-ups.

**Primary customers** → full seasonal weight curve  
**Household additions** → blended curve: `0.5 × seasonal_weight + 0.5 × uniform`
to dampen spikes (household additions are organic referrals, not demand-driven)

### Implementation Plan

**Phase A — CSV bootstrap (fast prototype, no order run needed)**
- Modify `samples/simulator_base_data.ipynb` to generate `created_at` using
  the seasonal sampler instead of a flat random date
- Add a `household_id` column to `customers.csv` grouping members by address
- Enforce household ordering: member `created_at` ≥ primary's `created_at`
- Validate in `notebooks/01_simulator_data_quality.ipynb`:
  histogram of `created_at` by month should mirror order seasonality

**Phase B — Runtime injection (stream mode)**
> ⚠️ **Superseded by ADR-018.** Phase B is removed from scope. Customer pool growth is handled by pre-generating customers with forward-looking `created_at` dates. Stream mode filters `created_at <= current_sim_time` — no runtime injection needed.

### Config Knobs (`simulation:` section)
```yaml
customer_acquisition:
  household_seasonality_blend: 0.5   # 0=fully seasonal, 1=fully flat
  p_household_addition: 0.30         # probability new customer joins existing household
  max_household_size: 9
```

### Validation Query
```sql
-- created_at distribution should mirror order seasonality
SELECT DATE_TRUNC('month', created_at)::DATE AS month, COUNT(*) AS new_customers
FROM customers GROUP BY 1 ORDER BY 1;

-- No household exceeds cap
SELECT address_id, COUNT(*) AS members FROM customers
GROUP BY address_id HAVING members > 9;
```

---

## Lever 2 — Product Lifecycle (Stars, Duds, Launch Spikes) ⏸ Deferred post-Phase 2

### Goal
Products should come online over the simulation window. A subset are "stars"
with a demand spike at launch that decays over weeks. "Duds" never gain
traction and stay in the long tail.

### Approach
Add `launched_at` and `product_tier` columns to `products.csv`.
Filter the active product pool per order date during history generation using
a date-sorted sliding window. Apply a time-varying weight multiplier for stars.

**Product tiers (assigned at CSV generation time):**
| Tier | % of catalogue | Behaviour |
|------|---------------|-----------|
| `star` | 5% | Launch spike: `weight × (1 + spike_factor × exp(-days_since_launch / decay_days))` |
| `normal` | 75% | Standard power-law weight, available from launch |
| `dud` | 20% | Weight floor (0.1× normal), available from launch |

### Implementation Plan

**Phase A — CSV generation**
- Add `launched_at` (spread across simulation window, earlier products more
  likely to be normal/dud, later ones can be any tier)
- Add `product_tier` column (`star` / `normal` / `dud`)
- Add `spike_factor` and `decay_days` columns (stars only; NULL for others)

**Phase B — Generator changes**
- `load_products()` returns `launched_at` and `product_tier`
- `generate_historical_orders()`: pre-sort orders by `order_date`; maintain
  a sliding `active_products` list — append products as `launched_at` passes.
  Recompute `product_weights` only when the active set changes (amortised cost).
- For stars: wrap base weight with the decay multiplier keyed on
  `(order_date - launched_at).days`
- Stream mode: check `launched_at <= now()` at each tick; add newly launched
  products to the in-memory pool

### Data Structure for Sliding Window
```
Sort products by launched_at ascending.
Keep pointer i into sorted list.
For each order_date (orders already sorted):
    while products[i].launched_at <= order_date: active_pool.append(products[i]); i++
    use active_pool for this order
```
O(n + p) total — no per-order full scan.

### Config Knobs
```yaml
product_lifecycle:
  star_pct: 0.05
  dud_pct:  0.20
  star_spike_factor: 8.0      # peak multiplier at launch
  star_decay_days:   21.0     # half-life of spike
  launch_spread_months: 20    # products launch across first N months of window
```

### Validation Query
```sql
-- Stars should show a spike in first 30 days post-launch then decay
SELECT
    p.name,
    DATEDIFF('day', p.launched_at, o.order_date) AS days_since_launch,
    COUNT(*) AS orders
FROM order_items oi
JOIN orders o USING (order_id)
JOIN products p USING (product_id)
WHERE p.product_tier = 'star' AND days_since_launch BETWEEN 0 AND 90
GROUP BY 1, 2 ORDER BY 1, 2;
```

---

## Lever 3 — Time-of-Day Distribution with Timezone ⏸ Deferred post-Phase 2

### Goal
Order timestamps should follow a realistic intra-day demand curve in the
customer's local time, rather than a flat random second within the day.

### Demand Curve (local time)
| Window | Weight | Notes |
|--------|--------|-------|
| 00:00–05:00 | 0.2 | Overnight trough |
| 05:00–08:00 | ramp 0.4→0.9 | Pre-work climb |
| 08:00–09:00 | 1.0 | Morning open |
| 09:00–11:00 | 1.1 | Mid-morning |
| 11:00–13:00 | 1.4 | Lunch peak |
| 13:00–16:00 | 1.1 | Afternoon |
| 16:00–18:00 | 1.2 | After-work tick up |
| 18:00–21:00 | 1.0→0.6 | Evening wind-down |
| 21:00–23:59 | 0.4 | Late night |

Perturbation: each day gets a random peak-shift of ±45 min and a noise
multiplier `~Uniform(0.85, 1.15)` per hour slot.

### Timezone Mapping
US state → UTC offset (standard time). DST applied via Python's `zoneinfo`.
```python
STATE_TZ = {
    "AK": "America/Anchorage",  "HI": "Pacific/Honolulu",
    "CA": "America/Los_Angeles", "OR": "America/Los_Angeles", ...
    "NY": "America/New_York",   "FL": "America/New_York", ...
    # ~50 entries, all US states
}
```
Customer timezone resolved from `customers.state` (join to addresses at
load time — `load_customers()` adds a `timezone` field).

### Implementation Plan
- Add `_intraday_weight(local_hour: float) -> float` — piecewise linear
  interpolation over the table above
- Add `_sample_order_time(local_tz: str, order_date: date) -> datetime` —
  samples a local hour using `_intraday_weight`, applies perturbation,
  converts to UTC
- Split `_sample_order_dates()` into two steps:
  1. Sample calendar day (seasonal weights) — existing logic
  2. Sample time-of-day (intraday curve in customer local time) — new
- `generate_order()` receives the customer's `timezone` field and uses it
  during time sampling
- `load_customers()` joins `addresses` to resolve and cache timezone per customer

### Config Knobs
```yaml
time_of_day:
  enabled: true
  peak_shift_minutes: 45      # max random shift of demand curve centre
  noise_factor: 0.15          # Uniform(1-noise, 1+noise) per hour slot
```

### Validation Query
```sql
-- Orders by hour of day in customer local time — should show the demand curve shape
SELECT
    HOUR(CONVERT_TIMEZONE(a.state_tz, o.order_date)) AS local_hour,
    COUNT(*) AS orders
FROM orders o
JOIN customers c USING (customer_id)
JOIN addresses a USING (address_id)
GROUP BY 1 ORDER BY 1;
```

---

## Delivery Sequence

| Order | Lever | Status | Notes |
|-------|-------|--------|-------|
| 1 | Customer acquisition | ✅ Complete | CSV regenerated; generator tail-spike bug fixed 2026-06-05 |
| 2 | Time-of-day | ⏸ Deferred | Self-contained — resume post-Phase 2 |
| 3 | Product lifecycle | ⏸ Deferred | Highest complexity — resume post-Phase 2 |

Each lever is independently mergeable. Levers 1 and 2 have no dependencies on
each other and could be developed in parallel if desired.

---

## Files Affected (summary)

| File | Levers |
|------|--------|
| `samples/simulator_base_data.ipynb` | 1, 3 |
| `simulator/config.yaml` | 1, 2, 3, compression_ratio |
| `simulator/generator.py` | 1, 2, 3 |
| `simulator/db.py` | 2 (launched_at), 3 (timezone join) |
| `simulator/main.py` | compression_ratio transition queue |
| `simulator/tests/test_generator.py` | 1, 2, 3 |
| `notebooks/01_simulator_data_quality.ipynb` | validation cells for all three |

---

## Stream Mode Architecture (ADR-019)

Stream mode no longer finalizes all lifecycle events at order creation time. Instead it maintains a **pending-transitions queue** so CDC consumers see state changes drip out over real wall-clock time at the configured compression ratio.

### Config

```yaml
stream:
  compression_ratio: 60     # 1 real second = 60 simulated seconds
  # derived cadences (for reference — computed at runtime):
  # simulated_day_real_seconds = 86400 / compression_ratio  →  1440 s (24 min)
```

### Transition Queue

```
PendingTransition:
  order_id
  next_state
  fire_at_real_time   # = now() + (simulated_delay / compression_ratio)
```

Each tick the stream loop:
1. Checks the queue for transitions with `fire_at_real_time <= now()`
2. Emits the state UPDATE to the DB (CDC picks it up)
3. Schedules the next transition for that order (if not terminal)
4. Places new orders and schedules their first transition (`placed → confirmed`)

### Eligible Customer Pool

```python
eligible = [c for c in all_customers if c.created_at <= sim_clock.now()]
```

`sim_clock.now()` advances at `compression_ratio × real_elapsed`. The pool grows automatically as `created_at` dates are crossed — no runtime injection required (ADR-018).

### CDC Steady-State Characterisation

At `compression_ratio: 60`, a 30-minute real session covers ~30 simulated hours:
- ~1–2 "daily" Snowflake Task batch cycles fire
- Orders placed early in the session complete their full lifecycle (placed → delivered) before session end
- At any point mid-session, orders exist in all lifecycle stages simultaneously — realistic CDC load
