from __future__ import annotations

import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.db import get_session_local
from app.main import create_app
from app.models import Job, JobArtifact, JobTimeReport
from app.services.job_queue import get_job_queue
from app.services.passphrase import hash_passphrase


class FakeQueuedJob:
    def __init__(self, job_id: str):
        self.id = job_id


class FakeQueue:
    def __init__(self):
        self.calls: list[dict] = []

    def enqueue(self, func: str, kwargs: dict, **options):
        job_id = f"rq_{len(self.calls) + 1}"
        self.calls.append({"func": func, "kwargs": kwargs, "options": options, "id": job_id})
        return FakeQueuedJob(job_id)


def make_client(tmp_path: Path) -> tuple[TestClient, FakeQueue]:
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'time_reports.db'}",
        pass_phrase_hash=hash_passphrase("weekly-secret"),
        pass_phrase_version="2026-W17",
        session_secret="test-secret",
        artifact_root=str(tmp_path / "artifacts"),
        workspace_root="/Users/xyc/Documents/codexwork",
        worker_job_timeout_seconds=2400,
    )
    app = create_app(settings)
    queue = FakeQueue()
    app.dependency_overrides[get_job_queue] = lambda: queue
    return TestClient(app), queue


def _write_raw_workbooks(raw_dir: Path) -> tuple[Path, Path]:
    raw_dir.mkdir(parents=True)
    autohome = raw_dir / "ZJ测试车原始口碑.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "购车口碑"
    sheet.append(["用户名", "来源链接", "购车地", "发表日期", "最满意", "最不满意", "评价详情"])
    sheet.append(["张三", "https://example.invalid/a", "上海浦东", "2026-03-01", "空间大", "内饰一般", "空间大，内饰一般"])
    sheet.append(["王五", "https://example.invalid/c", "杭州西湖", "2026-03-03", "底盘稳", "胎噪大", "底盘稳，胎噪大"])
    sheet.append(["赵六", "https://example.invalid/d", "广州天河", "", "配置高", "无", "无日期评论"])
    workbook.save(autohome)

    dcd = raw_dir / "DCD口碑_测试车.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "口碑明细"
    sheet.append(["用户名", "来源链接", "购车城市", "发布时间", "评价全文"])
    sheet.append(["李四", "https://example.invalid/b", "北京朝阳", "2026-03-02", "动力顺，车机偶发卡顿"])
    sheet.append(["孙七", "https://example.invalid/e", "深圳南山", "2026-03-04", "空间不错，续航一般"])
    workbook.save(dcd)
    return autohome, dcd


def seed_completed_job(tmp_path: Path, job_id: str = "job_time") -> tuple[Path, Path]:
    raw_dir = tmp_path / "artifacts" / job_id / "outputs" / "raw"
    autohome, dcd = _write_raw_workbooks(raw_dir)
    session = get_session_local()()
    try:
        session.add(
            Job(
                job_id=job_id,
                query="测试车",
                model_name="测试车",
                status="completed",
                current_stage="completed",
                degraded=False,
                passphrase_version="2026-W17",
            )
        )
        session.add_all(
            [
                JobArtifact(job_id=job_id, artifact_type="excel", artifact_path=str(autohome), source_stage="collecting_autohome"),
                JobArtifact(job_id=job_id, artifact_type="excel", artifact_path=str(dcd), source_stage="collecting_dcd"),
            ]
        )
        session.commit()
    finally:
        session.close()
    return autohome, dcd


def authorize(client: TestClient) -> None:
    response = client.post("/api/access/verify", json={"passphrase": "weekly-secret"})
    assert response.status_code == 200


def test_comment_summary_and_preview_are_sanitized_and_date_filtered(tmp_path: Path) -> None:
    client, _queue = make_client(tmp_path)
    seed_completed_job(tmp_path)
    authorize(client)

    summary_response = client.get("/api/jobs/job_time/comments/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["date_min"] == "2026-03-01"
    assert summary["date_max"] == "2026-03-04"
    assert summary["total_count"] == 5
    assert summary["dated_count"] == 4
    assert summary["undated_count"] == 1
    assert summary["daily_counts"] == [
        {"date": "2026-03-01", "count": 1},
        {"date": "2026-03-02", "count": 1},
        {"date": "2026-03-03", "count": 1},
        {"date": "2026-03-04", "count": 1},
    ]

    preview_response = client.get("/api/jobs/job_time/comments?start_date=2026-03-02&end_date=2026-03-03&page=1&page_size=10")
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["total"] == 2
    serialized = json.dumps(preview, ensure_ascii=False)
    assert "张三" not in serialized
    assert "李四" not in serialized
    assert "example.invalid" not in serialized
    assert "北京朝阳" not in serialized
    assert [item["date"] for item in preview["items"]] == ["2026-03-02", "2026-03-03"]
    assert set(preview["items"][0]) == {"comment_id", "platform", "date", "model_name", "positive_text", "negative_text", "full_text"}


def test_create_and_read_time_report_enqueues_background_worker(tmp_path: Path) -> None:
    client, queue = make_client(tmp_path)
    seed_completed_job(tmp_path)
    authorize(client)

    create_response = client.post("/api/jobs/job_time/time-reports", json={"start_date": "2026-03-02", "end_date": "2026-03-03"})
    assert create_response.status_code == 200
    payload = create_response.json()
    assert payload["status"] == "queued"
    assert payload["sample_count"] == 2
    assert payload["platform_counts"] == {"汽车之家": 1, "懂车帝": 1}
    assert queue.calls[0]["func"] == "worker_jobs.run_time_report"
    assert queue.calls[0]["kwargs"]["report_id"] == payload["report_id"]

    list_response = client.get("/api/jobs/job_time/time-reports")
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["report_id"] == payload["report_id"]

    detail_response = client.get(f"/api/jobs/job_time/time-reports/{payload['report_id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["date_range"] == {"start_date": "2026-03-02", "end_date": "2026-03-03"}


def test_create_time_report_rejects_empty_date_range(tmp_path: Path) -> None:
    client, queue = make_client(tmp_path)
    seed_completed_job(tmp_path)
    authorize(client)

    response = client.post("/api/jobs/job_time/time-reports", json={"start_date": "2026-04-01", "end_date": "2026-04-02"})

    assert response.status_code == 409
    assert response.json()["detail"] == "该时间范围内没有可分析评论"
    assert queue.calls == []


def test_time_report_detail_is_scoped_to_owning_job_and_zip_downloads_artifacts(tmp_path: Path) -> None:
    client, _queue = make_client(tmp_path)
    seed_completed_job(tmp_path, job_id="job_time")
    seed_completed_job(tmp_path, job_id="job_other")
    authorize(client)

    report_dir = tmp_path / "artifacts" / "job_time" / "outputs" / "time_reports" / "time_report_1"
    report_dir.mkdir(parents=True)
    final_report = report_dir / "final_report.json"
    summary = report_dir / "测试车_2026-03-02_2026-03-03_时间范围口碑摘要.xlsx"
    image = report_dir / "测试车_优点词云.png"
    terms = report_dir / "测试车_词云词项清单.xlsx"
    final_report.write_text('{"headline":"时间版一页纸"}', encoding="utf-8")
    summary.write_text("xlsx-placeholder", encoding="utf-8")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    terms.write_text("xlsx-placeholder", encoding="utf-8")

    session = get_session_local()()
    try:
        report = JobTimeReport(
            report_id="time_report_1",
            job_id="job_time",
            model_name="测试车",
            start_date="2026-03-02",
            end_date="2026-03-03",
            status="completed",
            sample_count=2,
            platform_counts={"汽车之家": 1, "懂车帝": 1},
            report_json={"headline": "时间版一页纸"},
            artifact_paths=[str(final_report), str(summary), str(image), str(terms)],
            source="hermes-local-aggregate",
        )
        session.add(report)
        session.commit()
    finally:
        session.close()

    forbidden = client.get("/api/jobs/job_other/time-reports/time_report_1")
    assert forbidden.status_code == 404

    zip_response = client.get("/api/jobs/job_time/time-reports/time_report_1/artifacts.zip")
    assert zip_response.status_code == 200
    with zipfile.ZipFile(BytesIO(zip_response.content)) as archive:
        names = set(archive.namelist())

    assert "final_report.json" in names
    assert "测试车_2026-03-02_2026-03-03_时间范围口碑摘要.xlsx" in names
    assert "测试车_优点词云.png" in names
    assert "测试车_词云词项清单.xlsx" in names
