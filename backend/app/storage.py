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


class MetricRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def insert(self, record: MetricRecord) -> None:
        with psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
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
                        topic_row[0],
                        record.metric_key,
                        record.numeric_value,
                        record.observed_at.astimezone(timezone.utc),
                        json.dumps(record.payload_json) if record.payload_json is not None else None,
                        record.raw_payload,
                    ),
                )
            conn.commit()
