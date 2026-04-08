from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "backend", "name": "mqttstat"}


@app.get("/api/metrics")
def get_metrics(limit: int = 50) -> list[dict]:
    settings = get_settings()
    repository = MetricRepository(settings.database_url)
    metrics = repository.get_recent_metrics(limit=limit)
    return [
        {
            "topic": m.topic,
            "metric_key": m.metric_key,
            "numeric_value": m.numeric_value,
            "raw_payload": m.raw_payload,
            "observed_at": m.observed_at.isoformat(),
        }
        for m in metrics
    ]
