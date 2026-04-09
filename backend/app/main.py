from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException, Path as PathParam, Query
from pydantic import BaseModel, Field, field_validator

from .config import Settings, get_settings
from .migrations import MigrationRunner
from .mqtt_client import MQTTIngestClient, TopicMap
from .storage import AlertRule, MetricRepository, MqttRuntimeConfig, TopicStats


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


class MqttConfigUpdateRequest(BaseModel):
    mqtt_host: str = Field(min_length=1, max_length=255)
    mqtt_port: int = Field(ge=1, le=65535)
    mqtt_username: str | None = Field(default=None, max_length=255)
    mqtt_password: str | None = Field(default=None, max_length=1024)
    mqtt_client_id: str = Field(min_length=1, max_length=255)

    @field_validator("mqtt_host", "mqtt_client_id")
    @classmethod
    def _must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("mqtt_username", "mqtt_password")
    @classmethod
    def _normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MqttConfigResponse(BaseModel):
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str | None
    mqtt_client_id: str
    has_password: bool
    updated_at: datetime | None


class MqttConfigTestResponse(BaseModel):
    ok: bool
    detail: str


class AlertRuleRequest(BaseModel):
    id: int | None = None
    topic: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    condition: str = Field(pattern="^(gt|lt|eq|gte|lte)$")
    threshold: float
    enabled: bool = True


class AlertRuleResponse(BaseModel):
    id: int
    topic: str
    metric: str
    condition: str
    threshold: float
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AlertHistoryResponse(BaseModel):
    id: int
    rule_id: int
    topic: str
    metric: str
    observed_value: float
    ts: datetime


class MQTTClientService:
    def __init__(self, repository: MetricRepository, topic_map: TopicMap, settings: Settings) -> None:
        self._repository = repository
        self._topic_map = topic_map
        self._lock = threading.Lock()
        self._active_config = settings
        self._client: MQTTIngestClient | None = None

    @property
    def active_config(self) -> Settings:
        return self._active_config

    def start(self) -> None:
        with self._lock:
            if self._client is not None:
                return
            self._client = MQTTIngestClient(
                host=self._active_config.mqtt_host,
                port=self._active_config.mqtt_port,
                username=self._active_config.mqtt_username,
                password=self._active_config.mqtt_password,
                client_id=self._active_config.mqtt_client_id,
                topic_map=self._topic_map,
                repository=self._repository,
            )
            self._client.start()

    def reload_alerts(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.reload_rules()

    def stop(self) -> None:
        with self._lock:
            if self._client is None:
                return
            self._client.stop()
            self._client = None

    def reload(self, settings: Settings) -> None:
        with self._lock:
            if self._client is not None:
                self._client.stop()
            self._active_config = settings
            self._client = MQTTIngestClient(
                host=self._active_config.mqtt_host,
                port=self._active_config.mqtt_port,
                username=self._active_config.mqtt_username,
                password=self._active_config.mqtt_password,
                client_id=self._active_config.mqtt_client_id,
                topic_map=self._topic_map,
                repository=self._repository,
            )
            self._client.start()


def _runtime_config_or_defaults(repository: MetricRepository, defaults: Settings) -> Settings:
    persisted = repository.get_mqtt_runtime_config()
    if persisted is None:
        return defaults
    return defaults.with_mqtt_runtime_override(
        mqtt_host=persisted.mqtt_host,
        mqtt_port=persisted.mqtt_port,
        mqtt_username=persisted.mqtt_username,
        mqtt_password=persisted.mqtt_password,
        mqtt_client_id=persisted.mqtt_client_id,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    migrations_dir = (Path(__file__).resolve().parent.parent / "migrations").resolve()
    MigrationRunner(settings.database_url, migrations_dir).run()

    repository = MetricRepository(settings.database_url)
    effective_settings = _runtime_config_or_defaults(repository, settings)

    topic_map = TopicMap.from_file(effective_settings.mqtt_topic_map_path)
    mqtt_service = MQTTClientService(repository=repository, topic_map=topic_map, settings=effective_settings)
    mqtt_service.start()

    app.state.repository = repository
    app.state.settings = settings
    app.state.mqtt_service = mqtt_service

    try:
        yield
    finally:
        mqtt_service.stop()


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


def _to_mqtt_response(config: MqttRuntimeConfig) -> MqttConfigResponse:
    return MqttConfigResponse(
        mqtt_host=config.mqtt_host,
        mqtt_port=config.mqtt_port,
        mqtt_username=config.mqtt_username,
        mqtt_client_id=config.mqtt_client_id,
        has_password=bool(config.mqtt_password),
        updated_at=config.updated_at,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "backend", "name": "mqttstat"}


@app.get("/api/config/mqtt", response_model=MqttConfigResponse, tags=["config"])
def get_mqtt_config() -> MqttConfigResponse:
    repository: MetricRepository = app.state.repository
    defaults: Settings = app.state.settings
    persisted = repository.get_mqtt_runtime_config()

    if persisted is None:
        config = MqttRuntimeConfig(
            mqtt_host=defaults.mqtt_host,
            mqtt_port=defaults.mqtt_port,
            mqtt_username=defaults.mqtt_username,
            mqtt_password=defaults.mqtt_password,
            mqtt_client_id=defaults.mqtt_client_id,
            updated_at=None,
        )
        return _to_mqtt_response(config)

    return _to_mqtt_response(persisted)


@app.put("/api/config/mqtt", response_model=MqttConfigResponse, tags=["config"])
def put_mqtt_config(payload: MqttConfigUpdateRequest) -> MqttConfigResponse:
    repository: MetricRepository = app.state.repository
    defaults: Settings = app.state.settings
    mqtt_service: MQTTClientService = app.state.mqtt_service

    persisted = repository.upsert_mqtt_runtime_config(
        MqttRuntimeConfig(
            mqtt_host=payload.mqtt_host,
            mqtt_port=payload.mqtt_port,
            mqtt_username=payload.mqtt_username,
            mqtt_password=payload.mqtt_password,
            mqtt_client_id=payload.mqtt_client_id,
        )
    )

    mqtt_service.reload(
        defaults.with_mqtt_runtime_override(
            mqtt_host=persisted.mqtt_host,
            mqtt_port=persisted.mqtt_port,
            mqtt_username=persisted.mqtt_username,
            mqtt_password=persisted.mqtt_password,
            mqtt_client_id=persisted.mqtt_client_id,
        )
    )

    return _to_mqtt_response(persisted)


@app.post("/api/config/mqtt/test", response_model=MqttConfigTestResponse, tags=["config"])
def test_mqtt_config(payload: MqttConfigUpdateRequest) -> MqttConfigTestResponse:
    test_client = MQTTIngestClient(
        host=payload.mqtt_host,
        port=payload.mqtt_port,
        username=payload.mqtt_username,
        password=payload.mqtt_password,
        client_id=f"{payload.mqtt_client_id}-test",
        topic_map=TopicMap({}),
        repository=app.state.repository,
    )

    try:
        test_client.start()
        test_client.stop()
        return MqttConfigTestResponse(ok=True, detail="Connection succeeded")
    except Exception as exc:
        return MqttConfigTestResponse(ok=False, detail=f"Connection failed: {exc}")


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


@app.get("/api/alerts/rules", response_model=list[AlertRuleResponse], tags=["alerts"])
def list_alert_rules() -> list[AlertRuleResponse]:
    repository: MetricRepository = app.state.repository
    rules = repository.list_alert_rules()
    return [
        AlertRuleResponse(
            id=r.id,
            topic=r.topic,
            metric=r.metric,
            condition=r.condition,
            threshold=r.threshold,
            enabled=r.enabled,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rules
    ]


@app.post("/api/alerts/rules", response_model=AlertRuleResponse, tags=["alerts"])
def create_alert_rule(payload: AlertRuleRequest) -> AlertRuleResponse:
    repository: MetricRepository = app.state.repository
    mqtt_service: MQTTClientService = app.state.mqtt_service
    rule = AlertRule(
        id=payload.id,
        topic=payload.topic,
        metric=payload.metric,
        condition=payload.condition,
        threshold=payload.threshold,
        enabled=payload.enabled,
    )
    saved = repository.upsert_alert_rule(rule)
    mqtt_service.reload_alerts()
    return AlertRuleResponse(
        id=saved.id,
        topic=saved.topic,
        metric=saved.metric,
        condition=saved.condition,
        threshold=saved.threshold,
        enabled=saved.enabled,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
    )


@app.delete("/api/alerts/rules/{rule_id}", status_code=204, tags=["alerts"])
def delete_alert_rule(rule_id: int) -> None:
    repository: MetricRepository = app.state.repository
    mqtt_service: MQTTClientService = app.state.mqtt_service
    repository.delete_alert_rule(rule_id)
    mqtt_service.reload_alerts()


@app.get("/api/alerts/history", response_model=list[AlertHistoryResponse], tags=["alerts"])
def get_alert_history(limit: int = Query(default=50, ge=1, le=200)) -> list[AlertHistoryResponse]:
    repository: MetricRepository = app.state.repository
    history = repository.get_alert_history(limit=limit)
    return [
        AlertHistoryResponse(
            id=h.id,
            rule_id=h.rule_id,
            topic=h.topic,
            metric=h.metric,
            observed_value=h.observed_value,
            ts=h.ts,
        )
        for h in history
    ]
