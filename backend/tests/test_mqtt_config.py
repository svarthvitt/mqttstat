from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
import pytest

from app.main import MqttConfigUpdateRequest, app


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
