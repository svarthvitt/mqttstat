from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.storage import AlertRule

@pytest.fixture
def client(monkeypatch):
    class FakeRepository:
        def __init__(self):
            self.rules = []

        def upsert_alert_rule(self, rule):
            new_rule = AlertRule(
                id=1,
                topic=rule.topic,
                metric=rule.metric,
                condition=rule.condition,
                threshold=rule.threshold,
                enabled=rule.enabled,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )
            self.rules.append(new_rule)
            return new_rule

    class FakeMqttService:
        def reload_alerts(self):
            pass

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = FakeRepository()
    app.state.mqtt_service = FakeMqttService()

    with TestClient(app) as c:
        yield c

    app.router.lifespan_context = original_lifespan

def test_create_alert_rule_success(client):
    payload = {
        "topic": "test/topic",
        "metric": "temperature",
        "condition": "gt",
        "threshold": 25.5
    }
    response = client.post("/api/alerts/rules", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["topic"] == "test/topic"
    assert data["metric"] == "temperature"
    assert data["condition"] == "gt"
    assert data["threshold"] == 25.5

def test_create_alert_rule_invalid_condition(client):
    payload = {
        "topic": "test/topic",
        "metric": "temperature",
        "condition": "invalid",
        "threshold": 25.5
    }
    response = client.post("/api/alerts/rules", json=payload)
    assert response.status_code == 422
