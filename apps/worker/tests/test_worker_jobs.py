from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import worker_jobs
import worker_app.stages as stages_module
from worker_app.artifacts import ensure_job_dirs
from worker_app.jobs import PipelineResult
from worker_app.stages import build_stage_commands, StageCommand


def test_run_job_uses_configured_stage_runner(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    stage = StageCommand(name="collecting_autohome", dependency_name="auto-koubei-collector", command=["echo"], cwd=tmp_path)

    class FakeStore:
        def __init__(self, _database_url: str):
            pass

        def fetch_job_inputs(self, _job_id: str):
            return SimpleNamespace(
                model_name="测试车",
                autohome_series_id="8089",
                dongchedi_series_id="25398",
            )

        def handle_pipeline_event(self, _job_id: str, _event: dict):
            pass

    def fake_build_stage_runner():
        captured["builder_called"] = True
        return "runner-sentinel"

    def fake_run_pipeline(context, stage_commands, runner, observer):
        captured["context"] = context
        captured["stage_commands"] = stage_commands
        captured["runner"] = runner
        captured["observer"] = observer
        return PipelineResult(status="completed", degraded=False, completed_stages=["collecting_autohome"])

    monkeypatch.setattr(worker_jobs, "DatabaseJobStore", FakeStore)
    monkeypatch.setattr(worker_jobs, "ensure_job_dirs", lambda _root, _job_id: tmp_path)
    monkeypatch.setattr(worker_jobs, "build_stage_commands", lambda **_kwargs: [stage])
    monkeypatch.setattr(worker_jobs, "build_stage_runner", fake_build_stage_runner)
    monkeypatch.setattr(worker_jobs, "run_pipeline", fake_run_pipeline)

    result = worker_jobs.run_job(job_id="job_worker", database_url="sqlite://", artifact_root=str(tmp_path))

    assert captured["builder_called"] is True
    assert captured["runner"] == "runner-sentinel"
    assert captured["stage_commands"] == [stage]
    assert result["status"] == "completed"


def test_run_time_report_invokes_generator_and_persists_completion(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {"calls": []}

    class FakeStore:
        def __init__(self, _database_url: str):
            pass

        def fetch_time_report_inputs(self, report_id: str):
            captured["report_id"] = report_id
            return SimpleNamespace(
                report_id=report_id,
                job_id="job_worker",
                model_name="测试车",
                start_date="2026-03-01",
                end_date="2026-03-31",
            )

        def mark_time_report_running(self, report_id: str) -> None:
            captured["calls"].append(("running", report_id))

        def mark_time_report_completed(self, report_id: str, result: dict) -> None:
            captured["calls"].append(("completed", report_id, result))

        def mark_time_report_failed(self, report_id: str, error_code: str, error_message: str) -> None:
            captured["calls"].append(("failed", report_id, error_code, error_message))

    def fake_generate_time_report_outputs(**kwargs):
        captured["generator_kwargs"] = kwargs
        return {
            "status": "completed",
            "sample_count": 2,
            "platform_counts": {"汽车之家": 1, "懂车帝": 1},
            "report_json": {"headline": "时间范围报告"},
            "artifact_paths": [str(tmp_path / "final_report.json")],
            "source": "hermes",
        }

    monkeypatch.setattr(worker_jobs, "DatabaseJobStore", FakeStore)
    monkeypatch.setattr(worker_jobs, "generate_time_report_outputs", fake_generate_time_report_outputs)
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("HERMES_COMMAND", "hermes-test")

    result = worker_jobs.run_time_report(
        report_id="time_report_worker",
        database_url="sqlite://",
        artifact_root=str(tmp_path),
    )

    kwargs = captured["generator_kwargs"]
    assert kwargs["model_name"] == "测试车"
    assert kwargs["start_date"] == "2026-03-01"
    assert kwargs["end_date"] == "2026-03-31"
    assert kwargs["hermes_command"] == "hermes-test"
    assert kwargs["output_dir"] == tmp_path / "job_worker" / "outputs" / "time_reports" / "time_report_worker"
    assert kwargs["autohome_input"] == tmp_path / "job_worker" / "outputs" / "raw" / "ZJ测试车原始口碑.xlsx"
    assert kwargs["dcd_input"] == tmp_path / "job_worker" / "outputs" / "raw" / "DCD口碑_测试车.xlsx"
    assert captured["calls"][0] == ("running", "time_report_worker")
    assert captured["calls"][1][0:2] == ("completed", "time_report_worker")
    assert result["status"] == "completed"


def test_run_time_report_marks_failed_without_raising(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {"calls": []}

    class FakeStore:
        def __init__(self, _database_url: str):
            pass

        def fetch_time_report_inputs(self, report_id: str):
            return SimpleNamespace(
                report_id=report_id,
                job_id="job_worker",
                model_name="测试车",
                start_date="2026-04-01",
                end_date="2026-04-30",
            )

        def mark_time_report_running(self, report_id: str) -> None:
            captured["calls"].append(("running", report_id))

        def mark_time_report_completed(self, report_id: str, result: dict) -> None:
            captured["calls"].append(("completed", report_id, result))

        def mark_time_report_failed(self, report_id: str, error_code: str, error_message: str) -> None:
            captured["calls"].append(("failed", report_id, error_code, error_message))

    def fake_generate_time_report_outputs(**_kwargs):
        raise ValueError("no_comments_in_date_range")

    monkeypatch.setattr(worker_jobs, "DatabaseJobStore", FakeStore)
    monkeypatch.setattr(worker_jobs, "generate_time_report_outputs", fake_generate_time_report_outputs)

    result = worker_jobs.run_time_report(
        report_id="time_report_empty",
        database_url="sqlite://",
        artifact_root=str(tmp_path),
    )

    assert captured["calls"][0] == ("running", "time_report_empty")
    assert captured["calls"][1] == ("failed", "time_report_empty", "no_comments_in_date_range", "no_comments_in_date_range")
    assert result == {
        "report_id": "time_report_empty",
        "status": "failed",
        "error_code": "no_comments_in_date_range",
        "error_message": "no_comments_in_date_range",
    }


def make_dependency_map(tmp_path: Path) -> dict[str, dict[str, str]]:
    return {
        "auto-koubei-collector": {"path": str(tmp_path), "entrypoint": "auto.py"},
        "dcd-koubei-collector": {"path": str(tmp_path), "entrypoint": "dcd.py"},
        "koubei-postprocess": {"path": str(tmp_path), "entrypoint": "post.py"},
        "koubei-keyword-summary-skill": {"path": str(tmp_path), "entrypoint": "summary.py"},
        "koubei-wordcloud": {"path": str(tmp_path), "entrypoint": "wordcloud.py"},
    }


def test_wordcloud_stage_omits_missing_default_font_path(monkeypatch, tmp_path: Path) -> None:
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_font")
    monkeypatch.setattr(stages_module, "WORDCLOUD_FONT_PATH", str(tmp_path / "missing.ttc"))

    stages = build_stage_commands(
        job_paths=job_paths,
        model_name="测试车",
        autohome_series_id="8089",
        dongchedi_series_id="25398",
        dependency_map=make_dependency_map(tmp_path),
    )

    hermes_stage = next(stage for stage in stages if stage.name == "generating_hermes_outputs")
    assert "--font-path" not in hermes_stage.command


def test_wordcloud_stage_uses_configured_font_path(monkeypatch, tmp_path: Path) -> None:
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_font_configured")
    font_path = tmp_path / "font.ttc"
    font_path.write_bytes(b"font")
    monkeypatch.setattr(stages_module, "WORDCLOUD_FONT_PATH", str(font_path))

    stages = build_stage_commands(
        job_paths=job_paths,
        model_name="测试车",
        autohome_series_id="8089",
        dongchedi_series_id="25398",
        dependency_map=make_dependency_map(tmp_path),
    )

    hermes_stage = next(stage for stage in stages if stage.name == "generating_hermes_outputs")
    assert "--font-path" in hermes_stage.command
    font_path = hermes_stage.command[hermes_stage.command.index("--font-path") + 1]
    assert font_path == str(tmp_path / "font.ttc")


def test_build_stage_commands_uses_hermes_outputs_after_postprocess(monkeypatch, tmp_path: Path) -> None:
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_hermes")
    monkeypatch.setattr(stages_module, "WORDCLOUD_FONT_PATH", str(tmp_path / "missing.ttc"))

    stages = build_stage_commands(
        job_paths=job_paths,
        model_name="测试车",
        autohome_series_id="8089",
        dongchedi_series_id="25398",
        dependency_map=make_dependency_map(tmp_path),
    )

    stage_names = [stage.name for stage in stages]
    assert stage_names == [
        "collecting_autohome",
        "collecting_dcd",
        "postprocessing",
        "generating_hermes_outputs",
    ]
    hermes_stage = stages[-1]
    assert hermes_stage.dependency_name == "hermes-agent"
    assert hermes_stage.parse_json_stdout is True
    assert str(job_paths.outputs.summary / "测试车_双平台口碑摘要.xlsx") in hermes_stage.expected_artifacts
    assert str(job_paths.outputs.ai / "final_report.json") in hermes_stage.expected_artifacts
    assert str(job_paths.outputs.ai / "qa_chunks.json") in hermes_stage.expected_artifacts
    assert "--summary-script" in hermes_stage.command
    assert "--wordcloud-script" in hermes_stage.command
