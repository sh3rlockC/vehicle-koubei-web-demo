from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.db import get_session_local
from app.main import create_app
from app.models import Job, JobArtifact
from app.services.job_queue import get_job_queue
from app.services.passphrase import hash_passphrase


class FakeQueue:
    def enqueue(self, func: str, kwargs: dict):
        raise AssertionError("queue should not be used in QA tests")


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'qa.db'}",
        pass_phrase_hash=hash_passphrase("weekly-secret"),
        pass_phrase_version="2026-W17",
        session_secret="test-secret",
        artifact_root=str(tmp_path / "artifacts"),
        workspace_root="/Users/xyc/Documents/codexwork",
    )
    app = create_app(settings)
    app.dependency_overrides[get_job_queue] = lambda: FakeQueue()
    return TestClient(app)


def seed_result_job(job_id: str) -> None:
    fixture_root = Path("/Users/xyc/Documents/codexwork/data/26.4.7/风云X3 PLUS")
    session = get_session_local()()
    try:
        job = Job(
            job_id=job_id,
            query="风云X3 PLUS",
            model_name="风云X3 PLUS",
            status="completed",
            current_stage="completed",
            degraded=False,
            passphrase_version="2026-W17",
        )
        session.add(job)
        session.flush()
        session.add(
            JobArtifact(
                job_id=job_id,
                artifact_type="excel",
                artifact_path=str(fixture_root / "风云X3 PLUS_双平台口碑摘要.xlsx"),
                source_stage="summarizing",
            )
        )
        session.commit()
    finally:
        session.close()


def test_result_endpoint_marks_qa_available_after_chunk_build(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    seed_result_job("job_qa_ready")
    verify = client.post("/api/access/verify", json={"passphrase": "weekly-secret"})
    assert verify.status_code == 200

    response = client.get("/api/jobs/job_qa_ready/result")
    assert response.status_code == 200
    payload = response.json()

    assert payload["qa_available"] is True


def test_job_qa_answers_grounded_question(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    seed_result_job("job_qa_answer")
    verify = client.post("/api/access/verify", json={"passphrase": "weekly-secret"})
    assert verify.status_code == 200

    response = client.post(
        "/api/jobs/job_qa_answer/qa",
        json={"question": "大家最不满意什么？"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["insufficient_evidence"] is False
    assert payload["citations"]
    assert payload["confidence"] in {"medium", "high"}
    assert "负向反馈" in payload["answer"] or "槽点" in payload["answer"] or "问题" in payload["answer"]


def test_job_qa_rejects_question_without_grounding(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    seed_result_job("job_qa_unknown")
    verify = client.post("/api/access/verify", json={"passphrase": "weekly-secret"})
    assert verify.status_code == 200

    response = client.post(
        "/api/jobs/job_qa_unknown/qa",
        json={"question": "明年销量会不会更高？"},
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["insufficient_evidence"] is True
    assert payload["citations"] == []
