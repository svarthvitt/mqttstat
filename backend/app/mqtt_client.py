from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import yaml

from .storage import MetricRecord, MetricRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JsonFieldMapping:
    metric_key: str
    field: str


@dataclass(frozen=True)
class TopicMapping:
    topic: str
    payload_type: str
    metric_key: str | None = None
    json_fields: tuple[JsonFieldMapping, ...] = ()
    qos: int = 0


class TopicMap:
    def __init__(self, mappings: dict[str, TopicMapping]) -> None:
        self._mappings = mappings

    @property
    def topics(self) -> list[tuple[str, int]]:
        return [(m.topic, m.qos) for m in self._mappings.values()]

    def get(self, topic: str) -> TopicMapping | None:
        return self._mappings.get(topic)

    @classmethod
    def from_file(cls, path: Path) -> "TopicMap":
        if not path.exists():
            raise FileNotFoundError(f"Topic mapping file not found: {path}")

        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() in {".yaml", ".yml"}:
            parsed = yaml.safe_load(raw)
        else:
            parsed = json.loads(raw)

        topics = parsed.get("topics", []) if isinstance(parsed, dict) else []
        mappings: dict[str, TopicMapping] = {}

        for entry in topics:
            topic = entry["topic"]
            payload_type = entry["payload_type"]
            qos = int(entry.get("qos", 0))

            if payload_type == "json":
                json_fields = tuple(
                    JsonFieldMapping(metric_key=item["metric_key"], field=item["field"])
                    for item in entry.get("fields", [])
                )
                mapping = TopicMapping(
                    topic=topic,
                    payload_type=payload_type,
                    json_fields=json_fields,
                    qos=qos,
                )
            elif payload_type == "raw_numeric":
                metric_key = entry["metric_key"]
                mapping = TopicMapping(
                    topic=topic,
                    payload_type=payload_type,
                    metric_key=metric_key,
                    qos=qos,
                )
            else:
                logger.warning("Unsupported payload_type=%s for topic=%s", payload_type, topic)
                continue

            mappings[topic] = mapping

        return cls(mappings)


class MQTTIngestClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        client_id: str,
        topic_map: TopicMap,
        repository: MetricRepository,
    ) -> None:
        self._topic_map = topic_map
        self._repository = repository

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username=username, password=password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._host = host
        self._port = port

    def start(self) -> None:
        logger.info("Connecting MQTT client to %s:%s", self._host, self._port)
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, *_: Any) -> None:
        for topic, qos in self._topic_map.topics:
            client.subscribe(topic, qos=qos)
            logger.info("Subscribed to topic=%s qos=%s", topic, qos)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, message: mqtt.MQTTMessage) -> None:
        topic = message.topic
        mapping = self._topic_map.get(topic)
        if not mapping:
            logger.debug("Skipping unmapped topic=%s", topic)
            return

        raw_payload = message.payload.decode("utf-8", errors="replace")
        observed_at = datetime.now(tz=timezone.utc)

        try:
            if mapping.payload_type == "json":
                self._handle_json(topic, raw_payload, observed_at, mapping)
            elif mapping.payload_type == "raw_numeric":
                self._handle_raw_numeric(topic, raw_payload, observed_at, mapping)
        except Exception:
            logger.exception("Failed processing MQTT message topic=%s payload=%s", topic, raw_payload)

    def _handle_json(self, topic: str, raw_payload: str, observed_at: datetime, mapping: TopicMapping) -> None:
        payload = json.loads(raw_payload)

        for field_mapping in mapping.json_fields:
            value = _extract_path(payload, field_mapping.field)
            numeric_value = float(value)
            self._repository.insert(
                MetricRecord(
                    topic=topic,
                    metric_key=field_mapping.metric_key,
                    numeric_value=numeric_value,
                    raw_payload=raw_payload,
                    observed_at=observed_at,
                    payload_json=payload,
                )
            )

    def _handle_raw_numeric(self, topic: str, raw_payload: str, observed_at: datetime, mapping: TopicMapping) -> None:
        numeric_value = float(raw_payload.strip())
        self._repository.insert(
            MetricRecord(
                topic=topic,
                metric_key=mapping.metric_key or topic,
                numeric_value=numeric_value,
                raw_payload=raw_payload,
                observed_at=observed_at,
            )
        )


def _extract_path(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Path '{field_path}' not found in payload")
        current = current[part]
    return current
