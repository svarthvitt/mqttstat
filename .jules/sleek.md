# Sleek's Journal - Architectural Debt & Refactoring Wins

## 2026-05-21 - Alert Condition Logic Refinement
**Clutter:** The `_check_alerts` method in `MQTTIngestClient` uses a repetitive `if/elif` chain to evaluate alert conditions (`gt`, `lt`, etc.).
**Refactoring Win:** Replacing the `if/elif` chain with a mapping to `operator` functions improves readability and extensibility. This is a high-traffic code path as it executes for every incoming MQTT message.

## 2026-05-22 - Time Window Resolution Simplification
**Clutter:** The `_resolve_time_window` function in `main.py` used a repetitive `if/elif` chain to calculate start times for different `TimeRange` values.
**Refactoring Win:** Consolidating the `TimeRange` to `timedelta` mappings into a constant dictionary `_TIME_RANGE_DELTAS` and simplifying the override logic makes the function more readable and easier to maintain.

## 2026-05-23 - Topic Stats Query Consolidation
**Clutter:** The `MetricRepository.stats` method used three separate database queries (aggregates, latest value, first value) and complex `if/else` logic to build SQL strings based on the optional `metric` filter.
**Refactoring Win:** Consolidating the logic into a single SQL query using a Common Table Expression (CTE) and subqueries reduces database round-trips from 3 to 1 and simplifies the Python code significantly by using named parameters to handle optional filtering.
