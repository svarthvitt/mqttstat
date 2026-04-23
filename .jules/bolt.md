## 2025-05-15 - [Anti-pattern: N+1 Dashboard KPIs]
**Learning:** The dashboard was calculating global KPIs by iterating over all topics and calling a per-topic `stats()` method. This resulted in 3N queries (where N is the number of topics).
**Action:** Always look for opportunities to aggregate global statistics in a single query when building summary views.

## 2025-05-15 - [Anti-pattern: Redundant lookup in high-frequency ingestion]
**Learning:** Every MQTT message insertion triggered a topic name to ID lookup via `INSERT ... ON CONFLICT` and `SELECT`. In a high-frequency system, this triples the database load.
**Action:** Use in-memory caching for static or slow-changing metadata (like topic IDs) to optimize hot paths.

## 2025-05-16 - [Optimization: Batched Timeseries Retrieval]
**Learning:** Requesting multiple timeseries independently caused an N+1 query bottleneck (2 queries per series). Consolidating these into a single query using PostgreSQL window functions (`ROW_NUMBER()`) significantly reduces database roundtrips and connection overhead.
**Action:** Always provide batch retrieval methods in the repository for resources commonly requested in groups (like dashboard charts).

## 2025-05-16 - [Anti-pattern: Per-request Repository Instantiation]
**Learning:** Instantiating the repository within each API handler bypasses the internal in-memory topic ID cache, negating its performance benefits and adding overhead for every request.
**Action:** Share a single repository instance across the application (e.g., via `app.state` in FastAPI) to ensure cache persistence and connection efficiency.
