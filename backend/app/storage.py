from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import threading

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
        self._cache_lock = threading.Lock()

    def _get_topic_id(self, cur: psycopg.Cursor, topic: str, create: bool = False) -> int | None:
        """Helper to resolve topic_id using cache and optimized queries."""
        with self._cache_lock:
            tid = self._topic_id_cache.get(topic)
        if tid is not None:
            return tid

        if create:
            cur.execute(
                """
                WITH ins AS (
                    INSERT INTO topics (name) VALUES (%s)
                    ON CONFLICT (name) DO NOTHING RETURNING id
                )
                SELECT id FROM ins UNION ALL SELECT id FROM topics WHERE name = %s LIMIT 1
                """,
                (topic, topic),
            )
        else:
            cur.execute("SELECT id FROM topics WHERE name = %s", (topic,))

        row = cur.fetchone()
        if row:
            tid = int(row[0])
            with self._cache_lock:
                self._topic_id_cache[topic] = tid
            return tid
        return None

    def insert(self, record: MetricRecord) -> None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                topic_id = self._get_topic_id(cur, record.topic, create=True)
                if topic_id is None:
                    raise RuntimeError(f"Failed to resolve topic_id for {record.topic}")

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
        with self._cache_lock:
            if topic in self._topic_id_cache:
                return True
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                return self._get_topic_id(cur, topic) is not None

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
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                topic_id = self._get_topic_id(cur, topic)
                if topic_id is None:
                    return [], 0

                params: list[object] = [topic_id, start.astimezone(timezone.utc), end.astimezone(timezone.utc)]
                metric_filter = " AND metric = %s" if metric else ""
                query_params = tuple(params + ([metric] if metric else []))

                cur.execute(
                    f"SELECT COUNT(*) FROM measurements WHERE topic_id = %s AND ts >= %s AND ts <= %s{metric_filter}",
                    query_params,
                )
                total = int(cur.fetchone()[0])

                cur.execute(
                    f"""
                    SELECT ts, metric, value FROM measurements
                    WHERE topic_id = %s AND ts >= %s AND ts <= %s{metric_filter}
                    ORDER BY ts DESC LIMIT %s OFFSET %s
                    """,
                    query_params + (limit, offset),
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

    def stats(
        self,
        *,
        topic: str,
        start: datetime,
        end: datetime,
        metric: str | None,
    ) -> TopicStats:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                topic_id = self._get_topic_id(cur, topic)
                if topic_id is None:
                    return TopicStats(None, None, None, None, 0, None, None, None)

                params: list[object] = [topic_id, start.astimezone(timezone.utc), end.astimezone(timezone.utc)]
                metric_filter = " AND metric = %s" if metric else ""
                query_params = tuple(params + ([metric] if metric else []))

                # Consolidated 3 queries into 1 to reduce round-trips
                sql = f"""
                    SELECT
                        s.count, s.min, s.max, s.avg,
                        l.value AS latest_val, l.ts AS latest_ts,
                        f.value AS first_val, f.ts AS first_ts
                    FROM (
                        SELECT
                            COUNT(*) AS count,
                            MIN(value) AS min,
                            MAX(value) AS max,
                            AVG(value)::double precision AS avg
                        FROM measurements
                        WHERE topic_id = %s AND ts >= %s AND ts <= %s{metric_filter}
                    ) s
                    LEFT JOIN LATERAL (
                        SELECT value, ts FROM measurements
                        WHERE topic_id = %s AND ts >= %s AND ts <= %s{metric_filter}
                        ORDER BY ts DESC LIMIT 1
                    ) l ON TRUE
                    LEFT JOIN LATERAL (
                        SELECT value, ts FROM measurements
                        WHERE topic_id = %s AND ts >= %s AND ts <= %s{metric_filter}
                        ORDER BY ts ASC LIMIT 1
                    ) f ON TRUE
                """
                cur.execute(sql, query_params * 3)
                row = cur.fetchone()

        if not row or row[0] == 0:
            return TopicStats(None, None, None, None, 0, None, None, None)

        return TopicStats(
            latest=row[4],
            minimum=row[1],
            maximum=row[2],
            average=row[3],
            count=int(row[0]),
            first_value=row[6],
            first_observed_at=row[7],
            latest_observed_at=row[5],
        )

    def get_global_stats(
        self,
        *,
        start: datetime,
        end: datetime,
    ) -> TopicStats:
        """Fetch global KPIs in a single query with reduced round-trips."""
        params = [start.astimezone(timezone.utc), end.astimezone(timezone.utc)]
        sql = """
            SELECT
                s.count, s.min, s.max, s.avg,
                l.value AS latest_val, l.ts AS latest_ts,
                f.value AS first_val, f.ts AS first_ts
            FROM (
                SELECT
                    COUNT(*) AS count,
                    MIN(value) AS min,
                    MAX(value) AS max,
                    AVG(value)::double precision AS avg
                FROM measurements
                WHERE ts >= %s AND ts <= %s
            ) s
            LEFT JOIN LATERAL (
                SELECT value, ts FROM measurements
                WHERE ts >= %s AND ts <= %s
                ORDER BY ts DESC LIMIT 1
            ) l ON TRUE
            LEFT JOIN LATERAL (
                SELECT value, ts FROM measurements
                WHERE ts >= %s AND ts <= %s
                ORDER BY ts ASC LIMIT 1
            ) f ON TRUE
        """

        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params * 3)
                row = cur.fetchone()

        if not row or row[0] == 0:
            return TopicStats(None, None, None, None, 0, None, None, None)

        return TopicStats(
            latest=row[4],
            minimum=row[1],
            maximum=row[2],
            average=row[3],
            count=int(row[0]),
            first_value=row[6],
            first_observed_at=row[7],
            latest_observed_at=row[5],
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
