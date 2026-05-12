from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker_app.jobs import JobContext, StageResult, run_pipeline
from worker_app.stages import StageCommand, StageExecutionError


def make_stage(name: str, *, core: bool = True) -> StageCommand:
    return StageCommand(
        name=name,
        dependency_name=name,
        command=["echo", name],
        cwd=Path.cwd(),
        core=core,
    )


def test_pipeline_completes_when_all_stages_succeed(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("collecting_dcd"),
        make_stage("postprocessing"),
        make_stage("summarizing"),
    ]

    def runner(command, job_paths, progress_sink):
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_success", model_name="风云X3 PLUS", artifact_root=tmp_path),
        stage_commands,
        runner,
    )

    assert result.status == "completed"
    assert result.degraded is False
    assert result.completed_stages == [stage.name for stage in stage_commands]
    assert (tmp_path / "job_success" / "progress" / "progress.json").exists()


def test_pipeline_starts_collectors_concurrently(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("collecting_dcd"),
        make_stage("postprocessing"),
    ]
    autohome_started = threading.Event()
    dcd_started = threading.Event()
    completed: list[str] = []

    def runner(command, job_paths, progress_sink):
        if command.name == "collecting_autohome":
            autohome_started.set()
            assert dcd_started.wait(0.5), "dcd collector did not start before autohome finished"
        elif command.name == "collecting_dcd":
            dcd_started.set()
            assert autohome_started.wait(0.5), "autohome collector did not start before dcd finished"

        completed.append(command.name)
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_parallel_collectors", model_name="风云X3 PLUS", artifact_root=tmp_path),
        stage_commands,
        runner,
    )

    assert result.status == "completed"
    assert {"collecting_autohome", "collecting_dcd"}.issubset(completed)
    assert completed[-1] == "postprocessing"


def test_pipeline_degrades_when_non_core_stage_fails(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("collecting_dcd"),
        make_stage("summarizing"),
        make_stage("rendering_wordcloud", core=False),
    ]

    def runner(command, job_paths, progress_sink):
        if command.name == "rendering_wordcloud":
            raise StageExecutionError(stage=command.name, error_code="RENDER_ERROR", message="wordcloud failed")
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_degraded", model_name="风云X3 PLUS", artifact_root=tmp_path),
        stage_commands,
        runner,
    )

    assert result.status == "completed_degraded"
    assert result.degraded is True
    assert "summarizing" in result.completed_stages


def test_pipeline_degrades_when_stage_result_reports_degraded(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("collecting_dcd"),
        make_stage("postprocessing"),
        make_stage("generating_hermes_outputs"),
    ]

    def runner(command, job_paths, progress_sink):
        if command.name == "generating_hermes_outputs":
            return StageResult(status="degraded", artifact_paths=["/tmp/final_report.json"])
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_hermes_degraded", model_name="风云X3 PLUS", artifact_root=tmp_path),
        stage_commands,
        runner,
    )

    assert result.status == "completed_degraded"
    assert result.degraded is True
    assert result.completed_stages == [stage.name for stage in stage_commands]


def test_pipeline_falls_back_to_single_platform_once(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("collecting_dcd"),
        make_stage("postprocessing", core=True),
        make_stage("summarizing"),
    ]

    seen_commands: list[list[str]] = []

    stage_commands[2] = StageCommand(
        name="postprocessing",
        dependency_name="postprocessing",
        command=["echo", "postprocessing"],
        cwd=Path.cwd(),
        core=True,
        skip_in_single_platform=True,
    )
    stage_commands[3] = StageCommand(
        name="summarizing",
        dependency_name="summarizing",
        command=["echo", "dual-summary"],
        fallback_command=["echo", "single-summary"],
        cwd=Path.cwd(),
        core=True,
    )

    def runner(command, job_paths, progress_sink):
        seen_commands.append(command.command)
        if command.name == "collecting_dcd":
            raise StageExecutionError(stage=command.name, error_code="NETWORK_ERROR", message="dcd failed")
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_single_platform", model_name="风云X3 PLUS", artifact_root=tmp_path),
        stage_commands,
        runner,
    )

    assert result.status == "completed_degraded"
    assert result.degraded is True
    assert result.completed_stages == ["collecting_autohome", "summarizing"]
    assert ["echo", "postprocessing"] not in seen_commands
    assert ["echo", "single-summary"] in seen_commands


def test_pipeline_falls_back_to_dcd_when_autohome_fails(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("collecting_dcd"),
        make_stage("postprocessing", core=True),
        make_stage("summarizing"),
    ]

    seen_commands: list[list[str]] = []

    stage_commands[2] = StageCommand(
        name="postprocessing",
        dependency_name="postprocessing",
        command=["echo", "postprocessing"],
        cwd=Path.cwd(),
        core=True,
        skip_in_single_platform=True,
    )
    stage_commands[3] = StageCommand(
        name="summarizing",
        dependency_name="summarizing",
        command=["echo", "dual-summary"],
        fallback_command=["echo", "autohome-summary"],
        fallback_commands_by_stage={"collecting_dcd": ["echo", "dcd-summary"]},
        cwd=Path.cwd(),
        core=True,
    )

    def runner(command, job_paths, progress_sink):
        seen_commands.append(command.command)
        if command.name == "collecting_autohome":
            raise StageExecutionError(stage=command.name, error_code="OPENCLAW_ARTIFACTS_MISSING", message="autohome missing")
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_dcd_single_platform", model_name="QQ3", artifact_root=tmp_path),
        stage_commands,
        runner,
    )

    assert result.status == "completed_degraded"
    assert result.degraded is True
    assert result.completed_stages == ["collecting_dcd", "summarizing"]
    assert ["echo", "postprocessing"] not in seen_commands
    assert ["echo", "dcd-summary"] in seen_commands


def test_pipeline_fails_when_core_stage_breaks_without_recovery(tmp_path: Path) -> None:
    stage_commands = [
        make_stage("collecting_autohome"),
        make_stage("postprocessing"),
        make_stage("summarizing"),
    ]

    def runner(command, job_paths, progress_sink):
        if command.name == "postprocessing":
            raise StageExecutionError(stage=command.name, error_code="CONTRACT_ERROR", message="bad workbook")
        return StageResult(status="success")

    result = run_pipeline(
        JobContext(job_id="job_failed", model_name="风云X3 PLUS", artifact_root=tmp_path, allow_single_platform_fallback=False),
        stage_commands,
        runner,
    )

    assert result.status == "failed"
    assert result.failed_stage == "postprocessing"
    assert result.error_code == "CONTRACT_ERROR"
