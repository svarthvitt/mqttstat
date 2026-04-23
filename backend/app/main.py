from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
import logging
from pathlib import Path
import threading
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp
from pydantic import BaseModel, Field, field_validator

from .config import Settings, get_settings
from .migrations import MigrationRunner
from .mqtt_client import MQTTIngestClient, TopicMap
from .storage import AlertRule, MetricRepository, MqttRuntimeConfig, TopicStats

request_logger = logging.getLogger("mqttstat.request")


class TimeRange(str, Enum):
    one_hour = "1h"
    twenty_four_hours = "24h"
    seven_days = "7d"
    thirty_days = "30d"
    custom = "custom"


class TopicItemResponse(BaseModel):
    id: str
    topic: str
    metric: str


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


class DashboardCard(BaseModel):
    key: str
    label: str
    value: str
    hint: str | None = None


class DashboardKPIS(BaseModel):
    latest: float | None = None
    min: float | None = None
    max: float | None = None
    avg: float | None = None
    count: int = 0
    trend_pct: float | None = None


class DashboardResponse(BaseModel):
    cards: list[DashboardCard]
    kpis: DashboardKPIS


class TimeseriesPoint(BaseModel):
    ts: datetime
    value: float


class TimeseriesEntry(BaseModel):
    id: str
    label: str
    color: str
    points: list[TimeseriesPoint]


class TimeseriesResponse(BaseModel):
    series: list[TimeseriesEntry]


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


class MqttServiceStatusResponse(BaseModel):
    connected: bool
    last_error: str | None = None
    last_attempt_at: datetime | None = None


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
        self._connected = False
        self._last_error: str | None = None
        self._last_attempt_at: datetime | None = None

    @property
    def active_config(self) -> Settings:
        return self._active_config

    def status(self) -> MqttServiceStatusResponse:
        with self._lock:
            return MqttServiceStatusResponse(
                connected=self._connected,
                last_error=self._last_error,
                last_attempt_at=self._last_attempt_at,
            )

    def _set_attempt_state(self, *, connected: bool, error: str | None = None) -> None:
        self._connected = connected
        self._last_error = error
        self._last_attempt_at = datetime.now(timezone.utc)

    def start(self) -> None:
        with self._lock:
            if self._client is not None:
                return
            candidate_client = MQTTIngestClient(
                host=self._active_config.mqtt_host,
                port=self._active_config.mqtt_port,
                username=self._active_config.mqtt_username,
                password=self._active_config.mqtt_password,
                client_id=self._active_config.mqtt_client_id,
                topic_map=self._topic_map,
                repository=self._repository,
            )
            try:
                candidate_client.start()
            except Exception as exc:
                self._set_attempt_state(connected=False, error=str(exc))
                try:
                    candidate_client.stop()
                except Exception:
                    request_logger.debug("mqtt startup cleanup failed", exc_info=True)
                self._client = None
                return
            self._client = candidate_client
            self._set_attempt_state(connected=True, error=None)

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
            self._connected = False

    def reload(self, settings: Settings) -> None:
        with self._lock:
            if self._client is not None:
                self._client.stop()
            self._active_config = settings
            candidate_client = MQTTIngestClient(
                host=self._active_config.mqtt_host,
                port=self._active_config.mqtt_port,
                username=self._active_config.mqtt_username,
                password=self._active_config.mqtt_password,
                client_id=self._active_config.mqtt_client_id,
                topic_map=self._topic_map,
                repository=self._repository,
            )
            try:
                candidate_client.start()
            except Exception as exc:
                self._set_attempt_state(connected=False, error=str(exc))
                try:
                    candidate_client.stop()
                except Exception:
                    request_logger.debug("mqtt reload cleanup failed", exc_info=True)
                self._client = None
                return
            self._client = candidate_client
            self._set_attempt_state(connected=True, error=None)


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
    mqtt_status = mqtt_service.status()
    if not mqtt_status.connected:
        request_logger.warning(
            "MQTT startup failed; running in degraded mode. error=%s",
            mqtt_status.last_error or "unknown_error",
        )

    app.state.repository = repository
    app.state.settings = settings
    app.state.mqtt_service = mqtt_service

    try:
        yield
    finally:
        mqtt_service.stop()


app = FastAPI(title="mqttstat API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestTracingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get("x-request-id") or str(uuid4())
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "")
        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message.get("status", 500))
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("utf-8")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = (perf_counter() - started_at) * 1000
            request_logger.info(
                "request completed method=%s path=%s status=%s duration_ms=%.2f request_id=%s",
                method,
                path,
                status_code,
                duration_ms,
                request_id,
            )


app.add_middleware(RequestTracingMiddleware)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_TIME_RANGE_DELTAS = {
    TimeRange.one_hour: timedelta(hours=1),
    TimeRange.twenty_four_hours: timedelta(hours=24),
    TimeRange.seven_days: timedelta(days=7),
    TimeRange.thirty_days: timedelta(days=30),
}


def _resolve_time_window(
    range_name: TimeRange,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    resolved_end = _to_utc(end) if end else now

    if range_name == TimeRange.custom and (start is None or end is None):
        raise HTTPException(
            status_code=422,
            detail="Custom range requires both start and end timestamps.",
        )

    if start:
        resolved_start = _to_utc(start)
    else:
        delta = _TIME_RANGE_DELTAS.get(range_name, timedelta(days=30))
        resolved_start = resolved_end - delta

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


@app.get("/api/dashboard", response_model=DashboardResponse, tags=["dashboard"])
def get_dashboard(
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    legacy_start: datetime | None = Query(default=None, alias="start"),
    legacy_end: datetime | None = Query(default=None, alias="end"),
) -> DashboardResponse:
    repository: MetricRepository = app.state.repository

    if (start is not None or end is not None) and (legacy_start is not None or legacy_end is not None):
        request_logger.debug(
            "dashboard request includes both canonical from/to and deprecated start/end; ignoring start/end"
        )

    effective_start = start if (start is not None or end is not None) else legacy_start
    effective_end = end if (start is not None or end is not None) else legacy_end

    now = datetime.now(timezone.utc)
    resolved_end = _to_utc(effective_end) if effective_end else now
    resolved_start = _to_utc(effective_start) if effective_start else resolved_end - timedelta(hours=24)

    # Simplified dashboard data - in a real app this would be more complex
    topics = repository.list_topics()
    total_measurements = sum(t.metric_count for t in topics)

    # Calculate global KPIs across all topics/metrics for the range
    # Using optimized global_stats to avoid N+1 queries
    stats = repository.get_global_stats(start=resolved_start, end=resolved_end)

    kpis = DashboardKPIS(
        latest=stats.latest,
        min=stats.minimum,
        max=stats.maximum,
        avg=stats.average,
        count=stats.count,
        trend_pct=None, # Trend across multiple topics is hard to define simply
    )

    cards = [
        DashboardCard(key="topics", label="Active Topics", value=str(len(topics))),
        DashboardCard(key="measurements", label="Total Measurements", value=str(total_measurements)),
    ]
    if topics:
        latest_topic = max(topics, key=lambda t: t.latest_observed_at or datetime.min.replace(tzinfo=timezone.utc))
        cards.append(DashboardCard(
            key="latest_topic",
            label="Most Recent Topic",
            value=latest_topic.name,
            hint=f"Updated {latest_topic.latest_observed_at.strftime('%H:%M:%S')}" if latest_topic.latest_observed_at else None
        ))

    return DashboardResponse(cards=cards, kpis=kpis)


@app.get("/api/timeseries", response_model=TimeseriesResponse, tags=["dashboard"])
def get_timeseries(
    request: Request,
    series: str = Query(description="Comma-separated list of topic:metric IDs"),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
) -> TimeseriesResponse:
    repository: MetricRepository = request.app.state.repository
    now = datetime.now(timezone.utc)
    resolved_end = _to_utc(end) if end else now
    resolved_start = _to_utc(start) if start else resolved_end - timedelta(hours=24)

    colors = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"]
    result_series = []

    ids = [s.strip() for s in series.split(",") if s.strip()]
    series_keys = []
    for s_id in ids:
        if ":" in s_id:
            series_keys.append(tuple(s_id.split(":", 1)))

    # Fetch all series in a single optimized query
    # Using unique keys for the batch call to avoid redundant work
    unique_keys = list(set(series_keys))
    batch_results = repository.history_batch(
        series_keys=unique_keys,
        start=resolved_start,
        end=resolved_end,
        limit_per_series=500,
    )

    # Map back to original requested order to maintain color/order consistency
    for i, (topic, metric) in enumerate(series_keys):
        series_id = f"{topic}:{metric}"
        records = batch_results.get((topic, metric), [])

        points = [
            TimeseriesPoint(ts=r.observed_at, value=r.value)
            for r in reversed(records) # Return in chronological order
        ]

        result_series.append(TimeseriesEntry(
            id=series_id,
            label=f"{topic} / {metric}",
            color=colors[i % len(colors)],
            points=points
        ))

    return TimeseriesResponse(series=result_series)


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


@app.get("/api/config/mqtt/status", response_model=MqttServiceStatusResponse, tags=["config"])
def get_mqtt_status() -> MqttServiceStatusResponse:
    mqtt_service: MQTTClientService = app.state.mqtt_service
    return mqtt_service.status()


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
    summary="List all unique topic-metric pairs",
    tags=["topics"],
)
def list_topics() -> TopicListResponse:
    repository: MetricRepository = app.state.repository
    items = repository.list_topic_metrics()
    return TopicListResponse(
        topics=[
            TopicItemResponse(
                id=item.id,
                topic=item.topic,
                metric=item.metric,
            )
            for item in items
        ]
    )


@app.get(
    "/api/topics/{topic}/history",
    response_model=HistoryResponse,
    summary="Topic measurement history",
    tags=["topics"],
)
def topic_history(
    request: Request,
    topic: str = PathParam(description="MQTT topic name."),
    range_name: TimeRange = Query(default=TimeRange.twenty_four_hours, alias="range"),
    start: datetime | None = Query(default=None, description="Optional start timestamp (ISO-8601)."),
    end: datetime | None = Query(default=None, description="Optional end timestamp (ISO-8601)."),
    metric: str | None = Query(default=None, description="Optional metric key filter."),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of records to return."),
    offset: int = Query(default=0, ge=0, description="Pagination offset."),
) -> HistoryResponse:
    repository: MetricRepository = request.app.state.repository
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
    request: Request,
    topic: str = PathParam(description="MQTT topic name."),
    range_name: TimeRange = Query(default=TimeRange.twenty_four_hours, alias="range"),
    start: datetime | None = Query(default=None, description="Optional start timestamp (ISO-8601)."),
    end: datetime | None = Query(default=None, description="Optional end timestamp (ISO-8601)."),
    metric: str | None = Query(default=None, description="Optional metric key filter."),
) -> StatsResponse:
    repository: MetricRepository = request.app.state.repository
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
