"""Smoke tests for the FastAPI app and DB connectivity endpoints."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_db():
    resp = client.get("/health/db")
    assert resp.status_code == 200
    assert resp.json()["database"] == "reachable"
