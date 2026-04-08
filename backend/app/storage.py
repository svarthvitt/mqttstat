from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg


@dataclass(frozen=True)
class MetricRecord:
    topic: str
    metric_key: str
    numeric_value: float
    raw_payload: str
    observed_at: datetime


class MetricRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def ensure_schema(self) -> None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mqtt_metric_records (
                        id BIGSERIAL PRIMARY KEY,
                        topic TEXT NOT NULL,
                        metric_key TEXT NOT NULL,
                        numeric_value DOUBLE PRECISION NOT NULL,
                        raw_payload TEXT NOT NULL,
                        observed_at TIMESTAMPTZ NOT NULL
                    );
                    """
                )
            conn.commit()

    def insert(self, record: MetricRecord) -> None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mqtt_metric_records (
                        topic,
                        metric_key,
                        numeric_value,
                        raw_payload,
                        observed_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        record.topic,
                        record.metric_key,
                        record.numeric_value,
                        record.raw_payload,
                        record.observed_at.astimezone(timezone.utc),
                    ),
                )
            conn.commit()
