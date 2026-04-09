from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from pydantic import BaseModel, Field

from .config import get_settings
from .migrations import MigrationRunner
from .mqtt_client import MQTTIngestClient, TopicMap
from .storage import MetricRepository, TopicStats


class TimeRange(str, Enum):
    one_hour = "1h"
    twenty_four_hours = "24h"
    seven_days = "7d"
    thirty_days = "30d"
    custom = "custom"


class TopicItemResponse(BaseModel):
    topic: str = Field(description="Topic name.")
    metric_count: int = Field(description="Total measurements available for this topic.")
    latest_observed_at: datetime | None = Field(
        default=None,
        description="Timestamp of the latest measurement for this topic.",
    )


class TopicListResponse(BaseModel):
    topics: list[TopicItemResponse]


class HistoryItemResponse(BaseModel):
    observed_at: datetime
    metric: str
    value: float


class HistoryResponse(BaseModel):
    topic: str
    metric: str | None
    range: TimeRange
    start: datetime
    end: datetime
    limit: int
    offset: int
    total: int
    items: list[HistoryItemResponse]


class TrendResponse(BaseModel):
    direction: str
    delta: float | None
    delta_percent: float | None


class StatsResponse(BaseModel):
    topic: str
    metric: str | None
    range: TimeRange
    start: datetime
    end: datetime
    latest: float | None
    min: float | None
    max: float | None
    avg: float | None
    count: int
    trend: TrendResponse


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


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _resolve_time_window(
    range_name: TimeRange,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    resolved_end = _to_utc(end) if end else now

    if range_name == TimeRange.custom:
        if start is None or end is None:
            raise HTTPException(
                status_code=422,
                detail="Custom range requires both start and end timestamps.",
            )
        resolved_start = _to_utc(start)
    elif range_name == TimeRange.one_hour:
        resolved_start = _to_utc(start) if start else resolved_end - timedelta(hours=1)
    elif range_name == TimeRange.twenty_four_hours:
        resolved_start = _to_utc(start) if start else resolved_end - timedelta(hours=24)
    elif range_name == TimeRange.seven_days:
        resolved_start = _to_utc(start) if start else resolved_end - timedelta(days=7)
    else:
        resolved_start = _to_utc(start) if start else resolved_end - timedelta(days=30)

    if resolved_end < resolved_start:
        raise HTTPException(status_code=422, detail="end must be greater than or equal to start.")

    return resolved_start, resolved_end


def _trend_from_stats(stats: TopicStats) -> TrendResponse:
    if stats.count < 2 or stats.first_value is None or stats.latest is None:
        return TrendResponse(direction="insufficient_data", delta=None, delta_percent=None)

    delta = stats.latest - stats.first_value
    if abs(delta) < 1e-12:
        direction = "flat"
    else:
        direction = "up" if delta > 0 else "down"

    if abs(stats.first_value) < 1e-12:
        delta_percent = None
    else:
        delta_percent = (delta / abs(stats.first_value)) * 100.0

    return TrendResponse(direction=direction, delta=delta, delta_percent=delta_percent)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "backend", "name": "mqttstat"}


@app.get(
    "/api/topics",
    response_model=TopicListResponse,
    summary="List all topics",
    tags=["topics"],
)
def list_topics() -> TopicListResponse:
    repository = MetricRepository(get_settings().database_url)
    topics = repository.list_topics()
    return TopicListResponse(
        topics=[
            TopicItemResponse(
                topic=item.name,
                metric_count=item.metric_count,
                latest_observed_at=item.latest_observed_at,
            )
            for item in topics
        ]
    )


@app.get(
    "/api/topics/{topic}/history",
    response_model=HistoryResponse,
    summary="Topic measurement history",
    tags=["topics"],
)
def topic_history(
    topic: str = PathParam(description="MQTT topic name."),
    range_name: TimeRange = Query(default=TimeRange.twenty_four_hours, alias="range"),
    start: datetime | None = Query(default=None, description="Optional start timestamp (ISO-8601)."),
    end: datetime | None = Query(default=None, description="Optional end timestamp (ISO-8601)."),
    metric: str | None = Query(default=None, description="Optional metric key filter."),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records to return."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
) -> HistoryResponse:
    repository = MetricRepository(get_settings().database_url)
    if not repository.topic_exists(topic):
        raise HTTPException(status_code=404, detail=f"Topic '{topic}' was not found.")

    resolved_start, resolved_end = _resolve_time_window(range_name=range_name, start=start, end=end)
    records, total = repository.history(
        topic=topic,
        start=resolved_start,
        end=resolved_end,
        metric=metric,
        limit=limit,
        offset=offset,
    )

    return HistoryResponse(
        topic=topic,
        metric=metric,
        range=range_name,
        start=resolved_start,
        end=resolved_end,
        limit=limit,
        offset=offset,
        total=total,
        items=[
            HistoryItemResponse(
                observed_at=record.observed_at,
                metric=record.metric,
                value=record.value,
            )
            for record in records
        ],
    )


@app.get(
    "/api/topics/{topic}/stats",
    response_model=StatsResponse,
    summary="Aggregated topic statistics",
    tags=["topics"],
)
def topic_stats(
    topic: str = PathParam(description="MQTT topic name."),
    range_name: TimeRange = Query(default=TimeRange.twenty_four_hours, alias="range"),
    start: datetime | None = Query(default=None, description="Optional start timestamp (ISO-8601)."),
    end: datetime | None = Query(default=None, description="Optional end timestamp (ISO-8601)."),
    metric: str | None = Query(default=None, description="Optional metric key filter."),
) -> StatsResponse:
    repository = MetricRepository(get_settings().database_url)
    if not repository.topic_exists(topic):
        raise HTTPException(status_code=404, detail=f"Topic '{topic}' was not found.")

    resolved_start, resolved_end = _resolve_time_window(range_name=range_name, start=start, end=end)
    stats = repository.stats(
        topic=topic,
        start=resolved_start,
        end=resolved_end,
        metric=metric,
    )
    trend = _trend_from_stats(stats)

    return StatsResponse(
        topic=topic,
        metric=metric,
        range=range_name,
        start=resolved_start,
        end=resolved_end,
        latest=stats.latest,
        min=stats.minimum,
        max=stats.maximum,
        avg=stats.average,
        count=stats.count,
        trend=trend,
    )
