## 2025-05-15 - [Anti-pattern: N+1 Dashboard KPIs]
**Learning:** The dashboard was calculating global KPIs by iterating over all topics and calling a per-topic `stats()` method. This resulted in 3N queries (where N is the number of topics).
**Action:** Always look for opportunities to aggregate global statistics in a single query when building summary views.

## 2025-05-15 - [Anti-pattern: Redundant lookup in high-frequency ingestion]
**Learning:** Every MQTT message insertion triggered a topic name to ID lookup via `INSERT ... ON CONFLICT` and `SELECT`. In a high-frequency system, this triples the database load.
**Action:** Use in-memory caching for static or slow-changing metadata (like topic IDs) to optimize hot paths.

## 2025-05-15 - [Optimization: Batch Ingestion and Repository Reuse]
**Learning:** High-frequency MQTT messages with multiple JSON fields triggered multiple database connections and redundant topic ID lookups. Batching inserts and reusing a single Repository instance with an in-memory cache significantly reduces database overhead.
**Action:** Use `executemany` for multi-record inserts and ensure Repository instances are shared across the application lifespan to leverage internal caches.
