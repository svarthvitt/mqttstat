## 2025-05-15 - [Anti-pattern: N+1 Dashboard KPIs]
**Learning:** The dashboard was calculating global KPIs by iterating over all topics and calling a per-topic `stats()` method. This resulted in 3N queries (where N is the number of topics).
**Action:** Always look for opportunities to aggregate global statistics in a single query when building summary views.

## 2025-05-15 - [Anti-pattern: Redundant lookup in high-frequency ingestion]
**Learning:** Every MQTT message insertion triggered a topic name to ID lookup via `INSERT ... ON CONFLICT` and `SELECT`. In a high-frequency system, this triples the database load.
**Action:** Use in-memory caching for static or slow-changing metadata (like topic IDs) to optimize hot paths.

## 2026-04-14 - [Optimization: Topic ID Caching and Joined Query Removal]
**Learning:** Querying a large timeseries table like `measurements` by joining on a metadata table (`topics`) on every request is inefficient. Caching the mapping of name to numeric ID in memory allows for O(1) lookup and simplified SQL queries that filter on indexed foreign keys.
**Action:** Use a private `_resolve_topic_id` helper with a dictionary cache for frequently accessed entities to avoid redundant JOINs in hot path queries.
