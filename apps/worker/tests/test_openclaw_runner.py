from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker_app.artifacts import ensure_job_dirs
from worker_app.jobs import StageResult
from worker_app.openclaw_runner import OpenClawSettings, build_stage_runner, run_autohome_via_openclaw, run_collector_via_openclaw
from worker_app.progress import ProgressSink
from worker_app.stages import StageCommand


def make_autohome_stage(tmp_path: Path) -> StageCommand:
    output = tmp_path / "jobs" / "job_openclaw" / "outputs" / "raw" / "ZJ测试车原始口碑.xlsx"
    progress = tmp_path / "jobs" / "job_openclaw" / "progress" / "collecting_autohome.progress.json"
    return StageCommand(
        name="collecting_autohome",
        dependency_name="auto-koubei-collector",
        command=[
            "python",
            "export_autohome_koubei.py",
            "--series-id",
            "8089",
            "--output",
            str(output),
            "--progress-file",
            str(progress),
        ],
        cwd=tmp_path,
        expected_artifacts=(str(output), str(output.with_suffix(".validation.json")), str(progress)),
        progress_file=str(progress),
    )


def make_dcd_stage(tmp_path: Path) -> StageCommand:
    output = tmp_path / "jobs" / "job_openclaw" / "outputs" / "raw" / "DCD口碑_测试车.xlsx"
    progress = tmp_path / "jobs" / "job_openclaw" / "progress" / "collecting_dcd.progress.json"
    return StageCommand(
        name="collecting_dcd",
        dependency_name="dcd-koubei-collector",
        command=[
            "python",
            "export_dcd_koubei.py",
            "--series-id",
            "25545",
            "--start-page",
            "1",
            "--output",
            str(output),
            "--progress-file",
            str(progress),
        ],
        cwd=tmp_path,
        expected_artifacts=(str(output), str(output.with_suffix(".validation.json")), str(progress)),
        optional_artifacts=(str(output.with_suffix(".failed-pages.json")),),
        progress_file=str(progress),
    )


def test_build_stage_runner_uses_direct_runner_when_openclaw_is_disabled(tmp_path: Path) -> None:
    stage = make_autohome_stage(tmp_path)
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_openclaw")
    progress_sink = ProgressSink(job_id="job_openclaw", progress_path=job_paths.progress / "progress.json", stages=[stage.name])

    calls: list[str] = []

    def direct_runner(command, _job_paths, _progress_sink):
        calls.append(command.name)
        return StageResult(status="success", artifact_paths=["direct"])

    runner = build_stage_runner(settings=OpenClawSettings(enabled=False), direct_runner=direct_runner)
    result = runner(stage, job_paths, progress_sink)

    assert calls == ["collecting_autohome"]
    assert result.artifact_paths == ["direct"]


def test_build_stage_runner_routes_only_configured_stages_when_openclaw_is_enabled(tmp_path: Path) -> None:
    dcd_stage = StageCommand(
        name="collecting_dcd",
        dependency_name="dcd-koubei-collector",
        command=["python", "dcd.py"],
        cwd=tmp_path,
    )
    settings = OpenClawSettings(enabled=True, stages=("collecting_autohome",))
    calls: list[str] = []

    def direct_runner(command, _job_paths, _progress_sink):
        calls.append(command.name)
        return StageResult(status="success", artifact_paths=["direct"])

    runner = build_stage_runner(settings=settings, direct_runner=direct_runner)
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_openclaw")
    progress_sink = ProgressSink(job_id="job_openclaw", progress_path=job_paths.progress / "progress.json", stages=[dcd_stage.name])

    result = runner(dcd_stage, job_paths, progress_sink)

    assert calls == ["collecting_dcd"]
    assert result.artifact_paths == ["direct"]


def test_run_autohome_via_openclaw_calls_gateway_agent_and_collects_artifacts(tmp_path: Path) -> None:
    container_root = tmp_path / "jobs"
    host_root = tmp_path / "host-jobs"
    stage = make_autohome_stage(tmp_path)
    job_paths = ensure_job_dirs(container_root, "job_openclaw")
    progress_sink = ProgressSink(job_id="job_openclaw", progress_path=job_paths.progress / "progress.json", stages=[stage.name])
    captured: dict[str, object] = {}

    class FakeGatewayClient:
        def call_agent(self, message: str, *, settings: OpenClawSettings, session_id: str | None = None, stage_name: str = "openclaw") -> dict:
            captured["message"] = message
            captured["settings"] = settings
            captured["session_id"] = session_id
            captured["stage_name"] = stage_name
            captured["method"] = "agent"
            captured["params"] = {"message": message, "agentId": settings.agent_id, "timeout": settings.timeout_seconds}
            assert settings.gateway_url == "ws://host.docker.internal:18790"
            for artifact in stage.expected_artifacts:
                Path(artifact).parent.mkdir(parents=True, exist_ok=True)
                Path(artifact).write_text("artifact", encoding="utf-8")
            return {"status": "completed"}

    result = run_autohome_via_openclaw(
        stage,
        job_paths,
        progress_sink,
        settings=OpenClawSettings(
            enabled=True,
            gateway_url="ws://host.docker.internal:18790",
            agent_id="main",
            collector_skill="sh3rlockC/auto-koubei-collector",
            timeout_seconds=1800,
            stages=("collecting_autohome",),
            artifact_root_container=str(container_root),
            artifact_root_host=str(host_root),
        ),
        gateway_client=FakeGatewayClient(),
    )

    assert captured["method"] == "agent"
    assert captured["stage_name"] == "collecting_autohome"
    assert captured["params"]["agentId"] == "main"
    assert captured["params"]["timeout"] == 1800
    message = captured["message"]
    assert "sh3rlockC/auto-koubei-collector" in message
    assert "series_id=8089" in message
    assert str(host_root / "job_openclaw" / "outputs" / "raw" / "ZJ测试车原始口碑.xlsx") in message
    assert str(host_root / "job_openclaw" / "progress" / "collecting_autohome.progress.json") in message
    assert set(result.artifact_paths) == set(stage.expected_artifacts + stage.optional_artifacts)
    assert result.output_metadata["openclaw_gateway_url"] == "ws://host.docker.internal:18790"


def test_run_collector_via_openclaw_supports_dcd_collection_contract(tmp_path: Path) -> None:
    container_root = tmp_path / "jobs"
    host_root = tmp_path / "host-jobs"
    stage = make_dcd_stage(tmp_path)
    job_paths = ensure_job_dirs(container_root, "job_openclaw")
    progress_sink = ProgressSink(job_id="job_openclaw", progress_path=job_paths.progress / "progress.json", stages=[stage.name])
    captured: dict[str, object] = {}

    class FakeGatewayClient:
        def call_agent(self, message: str, *, settings: OpenClawSettings, session_id: str | None = None, stage_name: str = "openclaw") -> dict:
            captured["message"] = message
            captured["stage_name"] = stage_name
            captured["session_id"] = session_id
            for artifact in stage.expected_artifacts:
                Path(artifact).parent.mkdir(parents=True, exist_ok=True)
                Path(artifact).write_text("artifact", encoding="utf-8")
            Path(stage.optional_artifacts[0]).write_text("[]", encoding="utf-8")
            return {"status": "completed"}

    result = run_collector_via_openclaw(
        stage,
        job_paths,
        progress_sink,
        settings=OpenClawSettings(
            enabled=True,
            dcd_collector_skill="sh3rlockC/dcd-koubei-collector",
            timeout_seconds=1800,
            stages=("collecting_autohome", "collecting_dcd"),
            artifact_root_container=str(container_root),
            artifact_root_host=str(host_root),
        ),
        gateway_client=FakeGatewayClient(),
    )

    message = captured["message"]
    assert captured["stage_name"] == "collecting_dcd"
    assert captured["session_id"] == "vehicle-koubei-job_openclaw-collecting_dcd"
    assert "sh3rlockC/dcd-koubei-collector" in message
    assert "series_id=25545" in message
    assert str(host_root / "job_openclaw" / "outputs" / "raw" / "DCD口碑_测试车.xlsx") in message
    assert str(host_root / "job_openclaw" / "outputs" / "raw" / "DCD口碑_测试车.failed-pages.json") in message
    assert set(result.artifact_paths) == set(stage.expected_artifacts + stage.optional_artifacts)
    assert result.output_metadata["openclaw_skill"] == "sh3rlockC/dcd-koubei-collector"


def test_run_autohome_via_openclaw_uses_job_scoped_session_id(tmp_path: Path) -> None:
    stage = make_autohome_stage(tmp_path)
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_openclaw")
    progress_sink = ProgressSink(job_id="job_openclaw", progress_path=job_paths.progress / "progress.json", stages=[stage.name])
    captured: dict[str, str | None] = {}

    class SessionGatewayClient:
        def call_agent(self, message: str, *, settings: OpenClawSettings, session_id: str | None = None, stage_name: str = "openclaw") -> dict:
            captured["session_id"] = session_id
            for artifact in stage.expected_artifacts:
                Path(artifact).parent.mkdir(parents=True, exist_ok=True)
                Path(artifact).write_text("artifact", encoding="utf-8")
            return {"status": "completed"}

    run_autohome_via_openclaw(
        stage,
        job_paths,
        progress_sink,
        settings=OpenClawSettings(enabled=True),
        gateway_client=SessionGatewayClient(),
    )

    assert captured["session_id"] == "vehicle-koubei-job_openclaw-collecting_autohome"


def test_run_autohome_via_openclaw_waits_for_artifacts_after_agent_acceptance(tmp_path: Path) -> None:
    stage = make_autohome_stage(tmp_path)
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_openclaw")
    progress_sink = ProgressSink(job_id="job_openclaw", progress_path=job_paths.progress / "progress.json", stages=[stage.name])

    class AsyncGatewayClient:
        def call_agent(self, message: str, *, settings: OpenClawSettings, session_id: str | None = None, stage_name: str = "openclaw") -> dict:
            def write_artifacts() -> None:
                time.sleep(0.05)
                for artifact in stage.expected_artifacts:
                    Path(artifact).parent.mkdir(parents=True, exist_ok=True)
                    Path(artifact).write_text("artifact", encoding="utf-8")

            threading.Thread(target=write_artifacts, daemon=True).start()
            return {"status": "accepted", "taskId": "task-1"}

    result = run_autohome_via_openclaw(
        stage,
        job_paths,
        progress_sink,
        settings=OpenClawSettings(enabled=True, timeout_seconds=2, artifact_poll_interval_seconds=0.01),
        gateway_client=AsyncGatewayClient(),
    )

    assert set(result.artifact_paths) == set(stage.expected_artifacts)
