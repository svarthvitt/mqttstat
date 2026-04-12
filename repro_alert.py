import httpx
import json

def test_create_alert_rule():
    base_url = "http://localhost:8000"
    payload = {
        "topic": "test/topic",
        "metric": "temperature",
        "condition": "gt",
        "threshold": 25.5
    }

    try:
        response = httpx.post(f"{base_url}/api/alerts/rules", json=payload)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_create_alert_rule()
