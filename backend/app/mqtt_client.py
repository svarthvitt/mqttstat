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
        # Cache alert rules by (topic, metric) for O(1) lookup
        self._alert_rules_cache: dict[tuple[str, str], list[AlertRule]] = {}

        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self._client.username_pw_set(username=username, password=password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._host = host
        self._port = port

    def start(self) -> None:
        logger.info("Connecting MQTT client to %s:%s", self._host, self._port)
        self.reload_rules()
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
        records = []

        for field_mapping in mapping.json_fields:
            value = _extract_path(payload, field_mapping.field)
            numeric_value = float(value)
            records.append(
                MetricRecord(
                    topic=topic,
                    metric_key=field_mapping.metric_key,
                    numeric_value=numeric_value,
                    raw_payload=raw_payload,
                    observed_at=observed_at,
                    payload_json=payload,
                )
            )

        # Batch insert all metrics from the JSON payload in one transaction
        self._repository.insert_batch(records)

        # Check alerts for each metric
        for record in records:
            self._check_alerts(record.topic, record.metric_key, record.numeric_value)

    def _handle_raw_numeric(self, topic: str, raw_payload: str, observed_at: datetime, mapping: TopicMapping) -> None:
        numeric_value = float(raw_payload.strip())
        metric_key = mapping.metric_key or topic
        self._repository.insert(
            MetricRecord(
                topic=topic,
                metric_key=metric_key,
                numeric_value=numeric_value,
                raw_payload=raw_payload,
                observed_at=observed_at,
            )
        )
        self._check_alerts(topic, metric_key, numeric_value)

    def reload_rules(self) -> None:
        try:
            rules = self._repository.get_active_alert_rules()
            new_cache: dict[tuple[str, str], list[AlertRule]] = {}
            for rule in rules:
                key = (rule.topic, rule.metric)
                if key not in new_cache:
                    new_cache[key] = []
                new_cache[key].append(rule)
            self._alert_rules_cache = new_cache
            logger.info("Alert rules cache reloaded: %d rules active", len(rules))
        except Exception:
            logger.exception("Failed to reload alert rules cache")

    def _check_alerts(self, topic: str, metric_key: str, value: float) -> None:
        try:
            rules = self._alert_rules_cache.get((topic, metric_key), [])
            for rule in rules:
                triggered = False
                if rule.condition == "gt" and value > rule.threshold:
                    triggered = True
                elif rule.condition == "lt" and value < rule.threshold:
                    triggered = True
                elif rule.condition == "eq" and value == rule.threshold:
                    triggered = True
                elif rule.condition == "gte" and value >= rule.threshold:
                    triggered = True
                elif rule.condition == "lte" and value <= rule.threshold:
                    triggered = True

                if triggered:
                    logger.warning("Alert triggered! Topic: %s, Metric: %s, Value: %s %s %s",
                                   topic, metric_key, value, rule.condition, rule.threshold)
                    self._repository.insert_alert_history(rule.id, value)
        except Exception:
            logger.exception("Failed to check alerts for topic=%s metric=%s", topic, metric_key)


def _extract_path(payload: dict[str, Any], field_path: str) -> Any:
    current: Any = payload
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Path '{field_path}' not found in payload")
        current = current[part]
    return current
