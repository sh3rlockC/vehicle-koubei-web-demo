from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.main import create_app
from app.services.passphrase import hash_passphrase


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'test.db'}",
        pass_phrase_hash=hash_passphrase("weekly-secret"),
        pass_phrase_version="2026-W17",
        session_secret="test-secret",
        workspace_root="/Users/xyc/Documents/codexwork",
    )
    return TestClient(create_app(settings))


def test_vehicle_resolve_returns_normalized_candidates(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    client.post("/api/access/verify", json={"passphrase": "weekly-secret"})

    sample_payload = {
        "query": "风云X3 PLUS",
        "autohome": {
            "best": {
                "series_id": "8089",
                "url": "https://k.autohome.com.cn/8089?dimensionid=10&order=0&yearid=0#listcontainer",
                "title": "风云X3 PLUS",
                "source": "fixture:autohome",
            },
            "candidates": [
                {
                    "series_id": "8089",
                    "url": "https://k.autohome.com.cn/8089?dimensionid=10&order=0&yearid=0#listcontainer",
                    "title": "风云X3 PLUS",
                    "source": "fixture:autohome",
                }
            ],
        },
        "dongchedi": {
            "best": {
                "series_id": "25398",
                "url": "https://www.dongchedi.com/auto/series/25398",
                "title": "风云X3 PLUS",
                "source": "fixture:dcd",
            },
            "candidates": [
                {
                    "series_id": "25398",
                    "url": "https://www.dongchedi.com/auto/series/25398",
                    "title": "风云X3 PLUS",
                    "source": "fixture:dcd",
                }
            ],
        },
    }

    monkeypatch.setattr("app.routes.vehicles.VehicleResolver.resolve", lambda self, query: sample_payload)

    response = client.post("/api/vehicles/resolve", json={"query": "风云X3 PLUS"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["autohome"]["best"]["series_id"] == "8089"
    assert payload["dongchedi"]["best"]["series_id"] == "25398"


def test_vehicle_resolve_rejects_malformed_service_output(tmp_path: Path, monkeypatch) -> None:
    client = make_client(tmp_path)
    client.post("/api/access/verify", json={"passphrase": "weekly-secret"})

    def raise_error(self, query: str):
        raise ValueError("bad resolver payload")

    monkeypatch.setattr("app.routes.vehicles.VehicleResolver.resolve", raise_error)

    response = client.post("/api/vehicles/resolve", json={"query": "风云X3 PLUS"})

    assert response.status_code == 502
    assert response.json()["detail"] == "bad resolver payload"


def test_job_creation_fails_without_confirmed_platform_candidates(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post("/api/access/verify", json={"passphrase": "weekly-secret"})

    response = client.post("/api/jobs", json={"query": "风云X3 PLUS"})

    assert response.status_code == 422
