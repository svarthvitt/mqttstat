# Sleek's Journal - Architectural Debt & Refactoring Wins

## 2026-05-21 - Alert Condition Logic Refinement
**Clutter:** The `_check_alerts` method in `MQTTIngestClient` uses a repetitive `if/elif` chain to evaluate alert conditions (`gt`, `lt`, etc.).
**Refactoring Win:** Replacing the `if/elif` chain with a mapping to `operator` functions improves readability and extensibility. This is a high-traffic code path as it executes for every incoming MQTT message.

## 2026-05-22 - Time Window Resolution Simplification
**Clutter:** The `_resolve_time_window` function in `main.py` used a repetitive `if/elif` chain to calculate start times for different `TimeRange` values.
**Refactoring Win:** Consolidating the `TimeRange` to `timedelta` mappings into a constant dictionary `_TIME_RANGE_DELTAS` and simplifying the override logic makes the function more readable and easier to maintain.

## 2026-05-23 - Metric Repository Query Consolidation
**Clutter:** The `history` and `stats` methods in `MetricRepository` used redundant `if/else` branching to handle the optional `metric` parameter, duplicating large SQL strings.
**Refactoring Win:** Using dynamic SQL fragments for the optional `WHERE` clause and parameter mapping significantly reduced code duplication and improved readability. This consolidation ensures that any future changes to the base query only need to be made in one place.
