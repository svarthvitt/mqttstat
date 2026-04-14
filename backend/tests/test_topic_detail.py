from contextlib import asynccontextmanager
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage import TopicStats, HistoryRecord

class FakeTopicRepository:
    def __init__(self) -> None:
        self.stats_calls = []
        self.history_calls = []

    def topic_exists(self, topic: str):
        return topic == "test_topic"

    def stats(self, *, topic, start, end, metric):
        self.stats_calls.append((topic, start, end, metric))
        return TopicStats(
            latest=10.5,
            minimum=5.0,
            maximum=15.0,
            average=10.0,
            count=100,
            first_value=5.0,
            first_observed_at=start,
            latest_observed_at=end,
        )

    def history(self, *, topic, start, end, metric, limit, offset):
        self.history_calls.append((topic, start, end, metric, limit, offset))
        return ([
            HistoryRecord(observed_at=start, metric="temp", value=5.0),
            HistoryRecord(observed_at=end, metric="temp", value=10.5),
        ], 2)

@pytest.fixture
def client():
    repository = FakeTopicRepository()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = repository

    client = TestClient(app)
    yield client, repository

    app.router.lifespan_context = original_lifespan

def test_get_topic_detail(client):
    test_client, repository = client
    response = test_client.get(
        "/api/topics/test_topic",
        params={"metric": "temp", "range": "1h"}
    )

    assert response.status_code == 200
    data = response.json()

    assert "series" in data
    assert "summary" in data
    assert data["summary"]["latest"] == 10.5
    assert data["summary"]["count"] == 100
    assert data["series"]["id"] == "test_topic:temp"
    assert len(data["series"]["points"]) == 2

    assert len(repository.stats_calls) == 1
    assert len(repository.history_calls) == 1
    assert repository.stats_calls[0][0] == "test_topic"
    assert repository.stats_calls[0][3] == "temp"

def test_get_topic_detail_not_found(client):
    test_client, _ = client
    response = test_client.get("/api/topics/non_existent")
    assert response.status_code == 404
