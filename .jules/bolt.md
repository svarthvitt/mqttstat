## 2025-05-15 - [Anti-pattern: N+1 Dashboard KPIs]
**Learning:** The dashboard was calculating global KPIs by iterating over all topics and calling a per-topic `stats()` method. This resulted in 3N queries (where N is the number of topics).
**Action:** Always look for opportunities to aggregate global statistics in a single query when building summary views.

## 2025-05-15 - [Anti-pattern: Redundant lookup in high-frequency ingestion]
**Learning:** Every MQTT message insertion triggered a topic name to ID lookup via `INSERT ... ON CONFLICT` and `SELECT`. In a high-frequency system, this triples the database load.
**Action:** Use in-memory caching for static or slow-changing metadata (like topic IDs) to optimize hot paths.

## 2026-05-02 - [Anti-pattern: Window functions for boundary lookups]
**Learning:** Using `ROW_NUMBER() OVER()` to find first/latest records in a consolidated query can be slower than separate `ORDER BY ... LIMIT 1` subqueries on large datasets because it may force a full sort of the result set.
**Action:** Use CTEs with `ORDER BY ... LIMIT 1` to fetch boundary values within a consolidated query to allow the database to use indexes effectively.
