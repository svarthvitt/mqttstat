from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .mqtt_client import MQTTIngestClient, TopicMap
from .storage import MetricRepository


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    repository = MetricRepository(settings.database_url)
    repository.ensure_schema()

    topic_map = TopicMap.from_file(settings.mqtt_topic_map_path)
    mqtt_client = MQTTIngestClient(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        username=settings.mqtt_username,
        password=settings.mqtt_password,
        client_id=settings.mqtt_client_id,
        topic_map=topic_map,
        repository=repository,
    )
    mqtt_client.start()

    try:
        yield
    finally:
        mqtt_client.stop()


app = FastAPI(title="mqttstat API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "backend", "name": "mqttstat"}
