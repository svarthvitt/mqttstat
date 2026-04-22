from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

import psycopg


@dataclass(frozen=True)
class MetricRecord:
    topic: str
    metric_key: str
    numeric_value: float
    raw_payload: str
    observed_at: datetime
    payload_json: dict | None = None


@dataclass(frozen=True)
class TopicMetricItem:
    id: str
    topic: str
    metric: str


@dataclass(frozen=True)
class TopicSummary:
    name: str
    metric_count: int
    latest_observed_at: datetime | None


@dataclass(frozen=True)
class HistoryRecord:
    observed_at: datetime
    metric: str
    value: float


@dataclass(frozen=True)
class TopicStats:
    latest: float | None
    minimum: float | None
    maximum: float | None
    average: float | None
    count: int
    first_value: float | None
    first_observed_at: datetime | None
    latest_observed_at: datetime | None


@dataclass(frozen=True)
class MqttRuntimeConfig:
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_client_id: str
    updated_at: datetime | None = None


@dataclass(frozen=True)
class AlertRule:
    id: int | None
    topic: str
    metric: str
    condition: str
    threshold: float
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class AlertHistoryRecord:
    id: int | None
    rule_id: int
    observed_value: float
    ts: datetime
    topic: str | None = None
    metric: str | None = None


class MetricRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        # Performance optimization: cache topic names to IDs to avoid redundant lookups
        self._topic_id_cache: dict[str, int] = {}

    def insert(self, record: MetricRecord) -> None:
        topic_id = self._topic_id_cache.get(record.topic)

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                if topic_id is None:
                    # Cache miss: ensure topic exists and get its ID
                    cur.execute(
                        """
                        INSERT INTO topics (name)
                        VALUES (%s)
                        ON CONFLICT (name) DO NOTHING
                        """,
                        (record.topic,),
                    )

                    cur.execute(
                        "SELECT id FROM topics WHERE name = %s",
                        (record.topic,),
                    )
                    topic_row = cur.fetchone()
                    if topic_row is None:
                        raise RuntimeError(f"Failed to resolve topic_id for topic={record.topic}")

                    topic_id = int(topic_row[0])
                    self._topic_id_cache[record.topic] = topic_id

                cur.execute(
                    """
                    INSERT INTO measurements (
                        topic_id,
                        metric,
                        value,
                        ts,
                        payload_json,
                        raw_payload
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        topic_id,
                        record.metric_key,
                        record.numeric_value,
                        record.observed_at.astimezone(timezone.utc),
                        json.dumps(record.payload_json) if record.payload_json is not None else None,
                        record.raw_payload,
                    ),
                )
            conn.commit()

    def list_topics(self) -> list[TopicSummary]:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        t.name,
                        COUNT(m.id) AS metric_count,
                        MAX(m.ts) AS latest_observed_at
                    FROM topics t
                    LEFT JOIN measurements m ON m.topic_id = t.id
                    GROUP BY t.name
                    ORDER BY t.name ASC
                    """
                )
                rows = cur.fetchall()

        return [
            TopicSummary(
                name=row[0],
                metric_count=row[1],
                latest_observed_at=row[2],
            )
            for row in rows
        ]

    def list_topic_metrics(self) -> list[TopicMetricItem]:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT
                        t.name,
                        m.metric
                    FROM topics t
                    JOIN measurements m ON m.topic_id = t.id
                    ORDER BY t.name ASC, m.metric ASC
                    """
                )
                rows = cur.fetchall()

        return [
            TopicMetricItem(
                id=f"{row[0]}:{row[1]}",
                topic=row[0],
                metric=row[1],
            )
            for row in rows
        ]

    def topic_exists(self, topic: str) -> bool:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM topics WHERE name = %s", (topic,))
                return cur.fetchone() is not None

    def history(
        self,
        *,
        topic: str,
        start: datetime,
        end: datetime,
        metric: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[HistoryRecord], int]:
        params: list[object] = [topic, start.astimezone(timezone.utc), end.astimezone(timezone.utc)]

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                if metric:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                          AND m.metric = %s
                        """,
                        tuple(params + [metric]),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                        """,
                        tuple(params),
                    )
                total = int(cur.fetchone()[0])

                if metric:
                    cur.execute(
                        """
                        SELECT m.ts, m.metric, m.value
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                          AND m.metric = %s
                        ORDER BY m.ts DESC
                        LIMIT %s
                        OFFSET %s
                        """,
                        tuple(params + [metric, limit, offset]),
                    )
                else:
                    cur.execute(
                        """
                        SELECT m.ts, m.metric, m.value
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                        ORDER BY m.ts DESC
                        LIMIT %s
                        OFFSET %s
                        """,
                        tuple(params + [limit, offset]),
                    )
                rows = cur.fetchall()

        records = [
            HistoryRecord(
                observed_at=row[0],
                metric=row[1],
                value=row[2],
            )
            for row in rows
        ]
        return records, total

    def history_batch(
        self,
        *,
        series_keys: list[tuple[str, str]],
        start: datetime,
        end: datetime,
        limit_per_series: int = 500,
    ) -> dict[tuple[str, str], list[HistoryRecord]]:
        """
        Batch fetch history for multiple topic/metric pairs in a single query.
        Uses a window function to enforce per-series limits.
        """
        if not series_keys:
            return {}

        topic_names = list(set(name for name, _ in series_keys))
        results: dict[tuple[str, str], list[HistoryRecord]] = {key: [] for key in series_keys}

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                # 1. Resolve topic IDs (utilizing cache)
                missing_names = [n for n in topic_names if n not in self._topic_id_cache]
                if missing_names:
                    cur.execute("SELECT name, id FROM topics WHERE name = ANY(%s)", (missing_names,))
                    for name, tid in cur.fetchall():
                        self._topic_id_cache[name] = tid

                # 2. Map series keys to (topic_id, metric) and prepare reverse lookup
                id_metric_pairs = []
                id_to_name = {}
                for name, metric in series_keys:
                    tid = self._topic_id_cache.get(name)
                    if tid is not None:
                        id_metric_pairs.append((tid, metric))
                        id_to_name[tid] = name

                if not id_metric_pairs:
                    return results

                # 3. Batch query with window function
                # We use tuple(id_metric_pairs) for the IN clause.
                # (col1, col2) IN ((v1, v2), (v3, v4)) is efficient and standard PG.
                query = """
                SELECT ts, metric, value, topic_id
                FROM (
                    SELECT m.ts, m.metric, m.value, m.topic_id,
                           ROW_NUMBER() OVER(PARTITION BY m.topic_id, m.metric ORDER BY m.ts DESC) as rn
                    FROM measurements m
                    WHERE (m.topic_id, m.metric) IN %s
                      AND m.ts >= %s
                      AND m.ts <= %s
                ) sub
                WHERE rn <= %s
                ORDER BY ts DESC
                """
                cur.execute(
                    query,
                    (
                        tuple(id_metric_pairs),
                        start.astimezone(timezone.utc),
                        end.astimezone(timezone.utc),
                        limit_per_series,
                    ),
                )
                rows = cur.fetchall()

                # 4. Group results
                for ts, metric, value, topic_id in rows:
                    topic_name = id_to_name.get(topic_id)
                    if topic_name:
                        key = (topic_name, metric)
                        if key in results:
                            results[key].append(HistoryRecord(observed_at=ts, metric=metric, value=value))

        return results

    def stats(
        self,
        *,
        topic: str,
        start: datetime,
        end: datetime,
        metric: str | None,
    ) -> TopicStats:
        params: list[object] = [topic, start.astimezone(timezone.utc), end.astimezone(timezone.utc)]

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                if metric:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) AS count,
                            MIN(m.value) AS minimum,
                            MAX(m.value) AS maximum,
                            AVG(m.value)::double precision AS average
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                          AND m.metric = %s
                        """,
                        tuple(params + [metric]),
                    )
                else:
                    cur.execute(
                        """
                        SELECT
                            COUNT(*) AS count,
                            MIN(m.value) AS minimum,
                            MAX(m.value) AS maximum,
                            AVG(m.value)::double precision AS average
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                        """,
                        tuple(params),
                    )
                aggregate_row = cur.fetchone()

                if metric:
                    cur.execute(
                        """
                        SELECT m.value, m.ts
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                          AND m.metric = %s
                        ORDER BY m.ts DESC
                        LIMIT 1
                        """,
                        tuple(params + [metric]),
                    )
                else:
                    cur.execute(
                        """
                        SELECT m.value, m.ts
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                        ORDER BY m.ts DESC
                        LIMIT 1
                        """,
                        tuple(params),
                    )
                latest_row = cur.fetchone()

                if metric:
                    cur.execute(
                        """
                        SELECT m.value, m.ts
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                          AND m.metric = %s
                        ORDER BY m.ts ASC
                        LIMIT 1
                        """,
                        tuple(params + [metric]),
                    )
                else:
                    cur.execute(
                        """
                        SELECT m.value, m.ts
                        FROM measurements m
                        JOIN topics t ON t.id = m.topic_id
                        WHERE t.name = %s
                          AND m.ts >= %s
                          AND m.ts <= %s
                        ORDER BY m.ts ASC
                        LIMIT 1
                        """,
                        tuple(params),
                    )
                first_row = cur.fetchone()

        return TopicStats(
            latest=latest_row[0] if latest_row else None,
            minimum=aggregate_row[1] if aggregate_row else None,
            maximum=aggregate_row[2] if aggregate_row else None,
            average=aggregate_row[3] if aggregate_row else None,
            count=int(aggregate_row[0] if aggregate_row else 0),
            first_value=first_row[0] if first_row else None,
            first_observed_at=first_row[1] if first_row else None,
            latest_observed_at=latest_row[1] if latest_row else None,
        )

    def get_global_stats(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> TopicStats:
        """
        Optimized method to fetch global KPIs across all topics/metrics in a single database connection.
        Used for the dashboard to avoid N+1 queries.
        """
        params = [start.astimezone(timezone.utc), end.astimezone(timezone.utc)]

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                # 1. Aggregates
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS count,
                        MIN(value) AS minimum,
                        MAX(value) AS maximum,
                        AVG(value)::double precision AS average
                    FROM measurements
                    WHERE ts >= %s AND ts <= %s
                    """,
                    params,
                )
                aggregate_row = cur.fetchone()

                # 2. Latest value (global)
                cur.execute(
                    """
                    SELECT value, ts
                    FROM measurements
                    WHERE ts >= %s AND ts <= %s
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    params,
                )
                latest_row = cur.fetchone()

                # 3. First value (global)
                cur.execute(
                    """
                    SELECT value, ts
                    FROM measurements
                    WHERE ts >= %s AND ts <= %s
                    ORDER BY ts ASC
                    LIMIT 1
                    """,
                    params,
                )
                first_row = cur.fetchone()

        return TopicStats(
            latest=latest_row[0] if latest_row else None,
            minimum=aggregate_row[1] if aggregate_row else None,
            maximum=aggregate_row[2] if aggregate_row else None,
            average=aggregate_row[3] if aggregate_row else None,
            count=int(aggregate_row[0] if aggregate_row else 0),
            first_value=first_row[0] if first_row else None,
            first_observed_at=first_row[1] if first_row else None,
            latest_observed_at=latest_row[1] if latest_row else None,
        )

    def get_mqtt_runtime_config(self) -> MqttRuntimeConfig | None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT mqtt_host, mqtt_port, mqtt_username, mqtt_password, mqtt_client_id, updated_at
                    FROM mqtt_runtime_config
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()

        if row is None:
            return None

        return MqttRuntimeConfig(
            mqtt_host=row[0],
            mqtt_port=row[1],
            mqtt_username=row[2],
            mqtt_password=row[3],
            mqtt_client_id=row[4],
            updated_at=row[5],
        )

    def list_alert_rules(self) -> list[AlertRule]:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, topic, metric, condition, threshold, enabled, created_at, updated_at
                    FROM alert_rules
                    ORDER BY created_at DESC
                    """
                )
                rows = cur.fetchall()
        return [
            AlertRule(
                id=row[0],
                topic=row[1],
                metric=row[2],
                condition=row[3],
                threshold=row[4],
                enabled=row[5],
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    def upsert_alert_rule(self, rule: AlertRule) -> AlertRule:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                if rule.id:
                    cur.execute(
                        """
                        UPDATE alert_rules
                        SET topic = %s, metric = %s, condition = %s, threshold = %s, enabled = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, topic, metric, condition, threshold, enabled, created_at, updated_at
                        """,
                        (rule.topic, rule.metric, rule.condition, rule.threshold, rule.enabled, rule.id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO alert_rules (topic, metric, condition, threshold, enabled)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id, topic, metric, condition, threshold, enabled, created_at, updated_at
                        """,
                        (rule.topic, rule.metric, rule.condition, rule.threshold, rule.enabled),
                    )
                row = cur.fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Failed to upsert alert rule")
        return AlertRule(
            id=row[0],
            topic=row[1],
            metric=row[2],
            condition=row[3],
            threshold=row[4],
            enabled=row[5],
            created_at=row[6],
            updated_at=row[7],
        )

    def delete_alert_rule(self, rule_id: int) -> None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM alert_rules WHERE id = %s", (rule_id,))
            conn.commit()

    def get_active_alert_rules(self) -> list[AlertRule]:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, topic, metric, condition, threshold, enabled, created_at, updated_at
                    FROM alert_rules
                    WHERE enabled = TRUE
                    """
                )
                rows = cur.fetchall()
        return [
            AlertRule(
                id=row[0],
                topic=row[1],
                metric=row[2],
                condition=row[3],
                threshold=row[4],
                enabled=row[5],
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    def insert_alert_history(self, rule_id: int, observed_value: float) -> None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO alert_history (rule_id, observed_value)
                    VALUES (%s, %s)
                    """,
                    (rule_id, observed_value),
                )
            conn.commit()

    def get_alert_history(self, limit: int = 50) -> list[AlertHistoryRecord]:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT h.id, h.rule_id, h.observed_value, h.ts, r.topic, r.metric
                    FROM alert_history h
                    JOIN alert_rules r ON h.rule_id = r.id
                    ORDER BY h.ts DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            AlertHistoryRecord(
                id=row[0],
                rule_id=row[1],
                observed_value=row[2],
                ts=row[3],
                topic=row[4],
                metric=row[5],
            )
            for row in rows
        ]

    def upsert_mqtt_runtime_config(self, config: MqttRuntimeConfig) -> MqttRuntimeConfig:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mqtt_runtime_config (
                        id,
                        mqtt_host,
                        mqtt_port,
                        mqtt_username,
                        mqtt_password,
                        mqtt_client_id,
                        updated_at
                    )
                    VALUES (1, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (id)
                    DO UPDATE SET
                        mqtt_host = EXCLUDED.mqtt_host,
                        mqtt_port = EXCLUDED.mqtt_port,
                        mqtt_username = EXCLUDED.mqtt_username,
                        mqtt_password = EXCLUDED.mqtt_password,
                        mqtt_client_id = EXCLUDED.mqtt_client_id,
                        updated_at = NOW()
                    RETURNING mqtt_host, mqtt_port, mqtt_username, mqtt_password, mqtt_client_id, updated_at
                    """,
                    (
                        config.mqtt_host,
                        config.mqtt_port,
                        config.mqtt_username,
                        config.mqtt_password,
                        config.mqtt_client_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

        if row is None:
            raise RuntimeError("Failed to persist MQTT runtime config")

        return MqttRuntimeConfig(
            mqtt_host=row[0],
            mqtt_port=row[1],
            mqtt_username=row[2],
            mqtt_password=row[3],
            mqtt_client_id=row[4],
            updated_at=row[5],
        )
