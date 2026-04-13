from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from app.main import MQTTClientService, MqttConfigUpdateRequest, app
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
            self._status = {
                "connected": True,
                "last_error": None,
                "last_attempt_at": datetime.now(timezone.utc),
            }

        def reload(self, settings):
            self.reloaded = settings

        def status(self):
            return self._status

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

        status_response = client.get("/api/config/mqtt/status")
        assert status_response.status_code == 200
        status_json = status_response.json()
        assert status_json["connected"] is True
        assert status_json["last_error"] is None
    finally:
        app.router.lifespan_context = original_lifespan


def test_mqtt_service_start_failure_keeps_service_available(monkeypatch):
    class FakeSettings:
        mqtt_host = "bad-host"
        mqtt_port = 1883
        mqtt_username = None
        mqtt_password = None
        mqtt_client_id = "bad-client"
        mqtt_topic_map_path = None
        database_url = "sqlite://"

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            raise RuntimeError("mqtt connect failed")

        def stop(self):
            return None

    class FakeRepository:
        pass

    monkeypatch.setattr("app.main.MQTTIngestClient", FakeClient)
    service = MQTTClientService(repository=FakeRepository(), topic_map=object(), settings=FakeSettings())

    service.start()
    status = service.status()
    assert status.connected is False
    assert status.last_error == "mqtt connect failed"
    assert status.last_attempt_at is not None


def test_mqtt_service_reload_success_after_failure(monkeypatch):
    class FakeSettings:
        mqtt_host = "broker.local"
        mqtt_port = 1883
        mqtt_username = None
        mqtt_password = None
        mqtt_client_id = "client-id"
        mqtt_topic_map_path = None
        database_url = "sqlite://"

    class FakeRepository:
        pass

    class FakeClient:
        fail = True

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            if FakeClient.fail:
                raise RuntimeError("connect failed")

        def stop(self):
            return None

    monkeypatch.setattr("app.main.MQTTIngestClient", FakeClient)
    service = MQTTClientService(repository=FakeRepository(), topic_map=object(), settings=FakeSettings())

    service.start()
    assert service.status().connected is False

    FakeClient.fail = False
    service.reload(FakeSettings())
    status = service.status()
    assert status.connected is True
    assert status.last_error is None


def test_mqtt_service_reload_failure_preserves_api_availability(monkeypatch):
    class FakeSettings:
        mqtt_host = "broker.local"
        mqtt_port = 1883
        mqtt_username = None
        mqtt_password = None
        mqtt_client_id = "client-id"
        mqtt_topic_map_path = None
        database_url = "sqlite://"

        def with_mqtt_runtime_override(self, **kwargs):
            data = {
                "mqtt_host": self.mqtt_host,
                "mqtt_port": self.mqtt_port,
                "mqtt_username": self.mqtt_username,
                "mqtt_password": self.mqtt_password,
                "mqtt_client_id": self.mqtt_client_id,
                "mqtt_topic_map_path": self.mqtt_topic_map_path,
                "database_url": self.database_url,
            }
            data.update(kwargs)
            return type("RuntimeSettings", (), data)()

    class FakeRepository:
        def __init__(self):
            self._config = None

        def get_mqtt_runtime_config(self):
            return self._config

        def upsert_mqtt_runtime_config(self, config):
            self._config = config
            return config

    class FailingMqttService:
        def __init__(self):
            self._status = {
                "connected": False,
                "last_error": "connect failed",
                "last_attempt_at": datetime.now(timezone.utc),
            }

        def reload(self, _settings):
            return None

        def status(self):
            return self._status

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = FakeRepository()
    app.state.settings = FakeSettings()
    app.state.mqtt_service = FailingMqttService()

    try:
        client = TestClient(app)
        put_response = client.put(
            "/api/config/mqtt",
            json={
                "mqtt_host": "bad-host",
                "mqtt_port": 1883,
                "mqtt_username": None,
                "mqtt_password": None,
                "mqtt_client_id": "client-id",
            },
        )
        assert put_response.status_code == 200
        health_response = client.get("/health")
        assert health_response.status_code == 200
    finally:
        app.router.lifespan_context = original_lifespan


def test_app_starts_in_degraded_mode_when_mqtt_boot_fails(monkeypatch):
    class FakeSettings:
        database_url = "postgresql://unused"
        mqtt_host = "bad-host"
        mqtt_port = 1883
        mqtt_username = None
        mqtt_password = None
        mqtt_client_id = "bad-client"
        mqtt_topic_map_path = None

        def with_mqtt_runtime_override(self, **kwargs):
            return self

    class FakeMigrationRunner:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            return None

    class FakeRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_mqtt_runtime_config(self):
            return None

    class FakeTopicMap:
        @classmethod
        def from_file(cls, _path):
            return object()

    class FakeIngestClient:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("boot connect failed")

        def stop(self):
            return None

    monkeypatch.setattr("app.main.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("app.main.MigrationRunner", FakeMigrationRunner)
    monkeypatch.setattr("app.main.MetricRepository", FakeRepository)
    monkeypatch.setattr("app.main.TopicMap", FakeTopicMap)
    monkeypatch.setattr("app.main.MQTTIngestClient", FakeIngestClient)

    with TestClient(app) as client:
        health_response = client.get("/health")
        assert health_response.status_code == 200
        status_response = client.get("/api/config/mqtt/status")
        assert status_response.status_code == 200
        assert status_response.json()["connected"] is False
