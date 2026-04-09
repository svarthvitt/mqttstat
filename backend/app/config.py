from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_client_id: str
    mqtt_topic_map_path: Path

    def with_mqtt_runtime_override(
        self,
        *,
        mqtt_host: str,
        mqtt_port: int,
        mqtt_username: str | None,
        mqtt_password: str | None,
        mqtt_client_id: str,
    ) -> "Settings":
        return Settings(
            database_url=self.database_url,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
            mqtt_username=mqtt_username,
            mqtt_password=mqtt_password,
            mqtt_client_id=mqtt_client_id,
            mqtt_topic_map_path=self.mqtt_topic_map_path,
        )



def get_settings() -> Settings:
    mqtt_topic_map = os.getenv("MQTT_TOPIC_MAP_PATH", "config/topic_mappings.yaml")
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://mqttstat:mqttstat@db:5432/mqttstat"),
        mqtt_host=os.getenv("MQTT_BROKER_HOST", "localhost"),
        mqtt_port=int(os.getenv("MQTT_BROKER_PORT", "1883")),
        mqtt_username=os.getenv("MQTT_BROKER_USER"),
        mqtt_password=os.getenv("MQTT_BROKER_PASS"),
        mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "mqttstat-backend"),
        mqtt_topic_map_path=Path(mqtt_topic_map),
    )
