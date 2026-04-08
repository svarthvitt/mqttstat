import unittest.mock
from fastapi.testclient import TestClient
import pytest
from backend.app.main import app

client = TestClient(app)

def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "backend"

@unittest.mock.patch("backend.app.main.MetricRepository")
@unittest.mock.patch("backend.app.main.get_settings")
def test_get_metrics(mock_get_settings, mock_repo_class):
    mock_settings = unittest.mock.MagicMock()
    mock_settings.database_url = "postgresql://user:pass@host:5432/db"
    mock_get_settings.return_value = mock_settings

    mock_repo = mock_repo_class.return_value
    mock_metric = unittest.mock.MagicMock()
    mock_metric.topic = "test/topic"
    mock_metric.metric_key = "test_key"
    mock_metric.numeric_value = 12.3
    mock_metric.raw_payload = '{"value": 12.3}'
    mock_metric.observed_at.isoformat.return_value = "2024-01-01T00:00:00Z"

    mock_repo.get_recent_metrics.return_value = [mock_metric]

    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["topic"] == "test/topic"
    assert data[0]["numeric_value"] == 12.3
