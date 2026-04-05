from fastapi.testclient import TestClient
from src.api.run_api import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_estimate_without_model_returns_503():
    # Without the model file, the API should fail gracefully with a clear error
    # rather than crashing — this tests that the error handling works as intended
    response = client.post("/estimate", json={
        "surface_m2": 50.0,
        "rooms": 2,
        "arrondissement": 11
    })
    assert response.status_code == 503
