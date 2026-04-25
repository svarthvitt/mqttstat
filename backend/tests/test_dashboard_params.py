from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.storage import TopicStats, GlobalDashboardStats


def _utc(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


class FakeDashboardRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, datetime]] = []

    def list_topics(self):
        return []

    def get_global_stats(self, *, start: datetime, end: datetime):
        self.calls.append((start, end))
        kpis = TopicStats(
            latest=None,
            minimum=None,
            maximum=None,
            average=None,
            count=0,
            first_value=None,
            first_observed_at=None,
            latest_observed_at=None,
        )
        return GlobalDashboardStats(
            kpis=kpis,
            total_topics=0,
            total_measurements=0,
            latest_topic_name=None
        )


def test_dashboard_accepts_canonical_from_to():
    repository = FakeDashboardRepository()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = repository

    try:
        client = TestClient(app)
        response = client.get(
            "/api/dashboard",
            params={"from": "2026-01-01T00:00:00Z", "to": "2026-01-01T01:00:00Z"},
        )
    finally:
        app.router.lifespan_context = original_lifespan

    assert response.status_code == 200
    assert repository.calls == [(_utc("2026-01-01T00:00:00Z"), _utc("2026-01-01T01:00:00Z"))]


def test_dashboard_accepts_legacy_start_end_aliases():
    repository = FakeDashboardRepository()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = repository

    try:
        client = TestClient(app)
        response = client.get(
            "/api/dashboard",
            params={"start": "2026-02-01T00:00:00Z", "end": "2026-02-01T01:00:00Z"},
        )
    finally:
        app.router.lifespan_context = original_lifespan

    assert response.status_code == 200
    assert repository.calls == [(_utc("2026-02-01T00:00:00Z"), _utc("2026-02-01T01:00:00Z"))]


def test_dashboard_prefers_canonical_over_legacy_when_both_present(caplog):
    repository = FakeDashboardRepository()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = repository

    try:
        caplog.set_level("DEBUG", logger="mqttstat.request")
        client = TestClient(app)
        response = client.get(
            "/api/dashboard",
            params={
                "from": "2026-03-01T00:00:00Z",
                "to": "2026-03-01T01:00:00Z",
                "start": "2026-03-02T00:00:00Z",
                "end": "2026-03-02T01:00:00Z",
            },
        )
    finally:
        app.router.lifespan_context = original_lifespan

    assert response.status_code == 200
    assert repository.calls == [(_utc("2026-03-01T00:00:00Z"), _utc("2026-03-01T01:00:00Z"))]
    assert "ignoring start/end" in caplog.text
