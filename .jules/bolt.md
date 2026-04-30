## 2025-05-15 - [Anti-pattern: N+1 Dashboard KPIs]
**Learning:** The dashboard was calculating global KPIs by iterating over all topics and calling a per-topic `stats()` method. This resulted in 3N queries (where N is the number of topics).
**Action:** Always look for opportunities to aggregate global statistics in a single query when building summary views.

## 2025-05-15 - [Anti-pattern: Redundant lookup in high-frequency ingestion]
**Learning:** Every MQTT message insertion triggered a topic name to ID lookup via `INSERT ... ON CONFLICT` and `SELECT`. In a high-frequency system, this triples the database load.
**Action:** Use in-memory caching for static or slow-changing metadata (like topic IDs) to optimize hot paths.

## 2025-05-15 - [Optimization: Single-trip Stats Retrieval]
**Learning:** Topic and global statistics were previously retrieved via three separate database queries (aggregates, latest, and first). Consolidating these into a single query using a CTE and subqueries reduces database round-trips from 3 to 1.
**Action:** Use PostgreSQL CTEs to group related but distinct temporal lookups (like first/latest) with aggregate calculations in a single round-trip.
