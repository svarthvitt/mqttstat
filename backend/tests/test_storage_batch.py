from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.storage import HistoryRecord

class FakeBatchRepository:
    def __init__(self):
        self.history_batch_calls = []

    def history_batch(self, series_filters, start, end, limit_per_series=500):
        self.history_batch_calls.append({
            "series_filters": series_filters,
            "start": start,
            "end": end,
            "limit_per_series": limit_per_series
        })

        results = {}
        for topic, metric in series_filters:
            # Return some fake data for each requested series
            results[(topic, metric)] = [
                HistoryRecord(
                    observed_at=datetime.now(timezone.utc) - timedelta(minutes=i),
                    metric=metric,
                    value=float(i)
                )
                for i in range(5)
            ]
        return results

@pytest.fixture
def client():
    repo = FakeBatchRepository()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.router.lifespan_context = noop_lifespan
    app.state.repository = repo

    with TestClient(app) as c:
        yield c, repo

    app.router.lifespan_context = original_lifespan

def test_get_timeseries_uses_batch_fetch(client):
    c, repo = client

    response = c.get(
        "/api/timeseries",
        params={
            "series": "room1:temp,room2:humidity",
            "from": "2024-01-01T00:00:00Z",
            "to": "2024-01-01T12:00:00Z"
        }
    )

    assert response.status_code == 200
    data = response.json()

    # Verify we got both series back
    assert len(data["series"]) == 2
    assert data["series"][0]["id"] == "room1:temp"
    assert data["series"][1]["id"] == "room2:humidity"

    # Verify that repo.history_batch was called exactly once (no N+1)
    assert len(repo.history_batch_calls) == 1
    call = repo.history_batch_calls[0]

    # Verify arguments to history_batch
    assert set(call["series_filters"]) == {("room1", "temp"), ("room2", "humidity")}
    assert call["limit_per_series"] == 500

    # Verify points are in chronological order (reversed from history_batch results)
    # history_batch returns [now, now-1m, now-2m...]
    # get_timeseries should reverse them to [now-4m, now-3m, ..., now]
    points = data["series"][0]["points"]
    assert len(points) == 5
    assert points[0]["value"] == 4.0
    assert points[-1]["value"] == 0.0
