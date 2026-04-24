# Sleek's Journal - Architectural Debt & Refactoring Wins

## 2026-05-21 - Alert Condition Logic Refinement
**Clutter:** The `_check_alerts` method in `MQTTIngestClient` uses a repetitive `if/elif` chain to evaluate alert conditions (`gt`, `lt`, etc.).
**Refactoring Win:** Replacing the `if/elif` chain with a mapping to `operator` functions improves readability and extensibility. This is a high-traffic code path as it executes for every incoming MQTT message.

## 2026-05-22 - Time Window Resolution Simplification
**Clutter:** The `_resolve_time_window` function in `main.py` used a repetitive `if/elif` chain to calculate start times for different `TimeRange` values.
**Refactoring Win:** Consolidating the `TimeRange` to `timedelta` mappings into a constant dictionary `_TIME_RANGE_DELTAS` and simplifying the override logic makes the function more readable and easier to maintain.

## 2026-05-23 - MetricRepository SQL Branching Refinement
**Clutter:** The `history` and `stats` methods in `MetricRepository` contained triple redundancy in query branching to handle the optional `metric` filter.
**Refactoring Win:** Using dynamic SQL fragments and shared parameter tuples eliminated the redundant `if/else` branching, reducing the methods' footprint while preserving identical logic.
