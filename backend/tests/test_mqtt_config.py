from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
import pytest

from app.main import MqttConfigUpdateRequest, app
from app.storage import MqttRuntimeConfig


@pytest.mark.parametrize(
    "payload",
    [
        {
            "mqtt_host": " broker.local ",
            "mqtt_port": 1883,
            "mqtt_username": " user ",
            "mqtt_password": " secret ",
            "mqtt_client_id": " client-1 ",
        },
        {
            "mqtt_host": "10.0.0.2",
            "mqtt_port": 8883,
            "mqtt_username": None,
            "mqtt_password": None,
            "mqtt_client_id": "collector",
        },
    ],
)
def test_mqtt_config_payload_is_normalized(payload):
    model = MqttConfigUpdateRequest.model_validate(payload)

    assert model.mqtt_host
    assert model.mqtt_client_id
    if payload["mqtt_username"]:
        assert model.mqtt_username == payload["mqtt_username"].strip()
    if payload["mqtt_password"]:
        assert model.mqtt_password == payload["mqtt_password"].strip()


def test_mqtt_config_payload_rejects_blank_host():
    with pytest.raises(ValueError):
        MqttConfigUpdateRequest.model_validate(
            {
                "mqtt_host": "   ",
                "mqtt_port": 1883,
                "mqtt_username": "user",
                "mqtt_password": "pass",
                "mqtt_client_id": "client-1",
            }
        )


def test_health_preflight_includes_cors_headers():
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    try:
        client = TestClient(app)
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    finally:
        app.router.lifespan_context = original_lifespan

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_mqtt_config_get_put_and_test_endpoints(monkeypatch):
    class FakeRepository:
        def __init__(self):
            self._config = None

        def get_mqtt_runtime_config(self):
            return self._config

        def upsert_mqtt_runtime_config(self, config):
            self._config = MqttRuntimeConfig(
                mqtt_host=config.mqtt_host,
                mqtt_port=config.mqtt_port,
                mqtt_username=config.mqtt_username,
                mqtt_password=config.mqtt_password,
                mqtt_client_id=config.mqtt_client_id,
                updated_at=config.updated_at,
            )
            return self._config

    class FakeSettings:
        mqtt_host = "default-broker.local"
        mqtt_port = 1883
        mqtt_username = "default-user"
        mqtt_password = "default-pass"
        mqtt_client_id = "default-client"

        def with_mqtt_runtime_override(self, **kwargs):
            data = {
                "mqtt_host": self.mqtt_host,
                "mqtt_port": self.mqtt_port,
                "mqtt_username": self.mqtt_username,
                "mqtt_password": self.mqtt_password,
                "mqtt_client_id": self.mqtt_client_id,
            }
            data.update(kwargs)
            return type("RuntimeSettings", (), data)()

    class FakeMqttService:
        def __init__(self):
            self.reloaded = None

        def reload(self, settings):
            self.reloaded = settings

    class FakeMqttClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    monkeypatch.setattr("app.main.MQTTIngestClient", FakeMqttClient)
    app.state.repository = FakeRepository()
    app.state.settings = FakeSettings()
    app.state.mqtt_service = FakeMqttService()

    try:
        client = TestClient(app)

        response = client.get("/api/config/mqtt")
        assert response.status_code == 200
        assert response.json()["mqtt_host"] == "default-broker.local"

        payload = {
            "mqtt_host": "10.10.0.5",
            "mqtt_port": 1884,
            "mqtt_username": "mqtt-user",
            "mqtt_password": "mqtt-pass",
            "mqtt_client_id": "collector-01",
        }

        put_response = client.put("/api/config/mqtt", json=payload)
        assert put_response.status_code == 200
        put_json = put_response.json()
        assert put_json["mqtt_host"] == payload["mqtt_host"]
        assert put_json["mqtt_port"] == payload["mqtt_port"]
        assert put_json["mqtt_username"] == payload["mqtt_username"]
        assert put_json["mqtt_client_id"] == payload["mqtt_client_id"]
        assert put_json["has_password"] is True

        get_after_put = client.get("/api/config/mqtt")
        assert get_after_put.status_code == 200
        assert get_after_put.json()["mqtt_host"] == payload["mqtt_host"]

        test_response = client.post("/api/config/mqtt/test", json=payload)
        assert test_response.status_code == 200
        test_json = test_response.json()
        assert test_json["ok"] is True
        assert "succeeded" in test_json["detail"]
    finally:
        app.router.lifespan_context = original_lifespan
