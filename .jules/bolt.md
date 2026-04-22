## 2025-05-15 - [Anti-pattern: N+1 Dashboard KPIs]
**Learning:** The dashboard was calculating global KPIs by iterating over all topics and calling a per-topic `stats()` method. This resulted in 3N queries (where N is the number of topics).
**Action:** Always look for opportunities to aggregate global statistics in a single query when building summary views.

## 2025-05-15 - [Anti-pattern: Redundant lookup in high-frequency ingestion]
**Learning:** Every MQTT message insertion triggered a topic name to ID lookup via `INSERT ... ON CONFLICT` and `SELECT`. In a high-frequency system, this triples the database load.
**Action:** Use in-memory caching for static or slow-changing metadata (like topic IDs) to optimize hot paths.

## 2025-05-16 - [Pattern: Batching Top-N with Window Functions]
**Learning:** Requesting historical data for multiple series often leads to N+1 queries. Standard SQL `LIMIT` applies to the whole result set, making it hard to batch.
**Action:** Use `ROW_NUMBER() OVER(PARTITION BY ... ORDER BY ...)` in a subquery to efficiently fetch per-group limits (e.g., last 500 points) for multiple series in a single round-trip.
