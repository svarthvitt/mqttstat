from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from .config import get_settings
from .migrations import MigrationRunner
from .mqtt_client import MQTTIngestClient, TopicMap
from .storage import MetricRepository


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    migrations_dir = (Path(__file__).resolve().parent.parent / "migrations").resolve()
    MigrationRunner(settings.database_url, migrations_dir).run()

    repository = MetricRepository(settings.database_url)

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
