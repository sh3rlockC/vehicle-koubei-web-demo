from __future__ import annotations

import json
import subprocess
from pathlib import Path

from worker_app.artifacts import JobPaths
from worker_app.jobs import StageResult
from worker_app.progress import ProgressSink
from worker_app.stages import StageCommand, StageExecutionError


def _write_stage_log(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _classify_error(command: StageCommand, stderr: str, stdout: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if command.name == "rendering_wordcloud":
        return "RENDER_ERROR"
    if "timeout" in text or "connection" in text or "max retries" in text:
        return "NETWORK_ERROR"
    if "__next_data__" in text or "页面中未找到" in text:
        return "PARSING_ERROR"
    if "不存在" in text or "missing" in text or "unsupported" in text:
        return "CONTRACT_ERROR"
    return "WORKER_ERROR"


def _collect_existing_artifacts(command: StageCommand, stdout: str) -> tuple[list[str], dict]:
    artifacts: list[str] = []
    metadata: dict = {}
    for artifact in command.expected_artifacts + command.optional_artifacts:
        if Path(artifact).exists():
            artifacts.append(artifact)

    if command.parse_json_stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise StageExecutionError(
                stage=command.name,
                error_code="CONTRACT_ERROR",
                message=f"invalid JSON stdout: {exc}",
            ) from exc
        metadata["stdout_json"] = payload
        for key in ("excel_path",):
            value = payload.get(key)
            if isinstance(value, str) and value:
                artifacts.append(value)
        for image_path in payload.get("image_paths", []):
            if isinstance(image_path, str):
                artifacts.append(image_path)

    unique_artifacts: list[str] = []
    seen: set[str] = set()
    for artifact in artifacts:
        if artifact not in seen:
            unique_artifacts.append(artifact)
            seen.add(artifact)

    missing = [artifact for artifact in command.expected_artifacts if not Path(artifact).exists()]
    if missing:
        raise StageExecutionError(
            stage=command.name,
            error_code="CONTRACT_ERROR",
            message=f"missing expected artifacts: {', '.join(missing)}",
        )
    return unique_artifacts, metadata


def run_stage_command(command: StageCommand, job_paths: JobPaths, progress_sink: ProgressSink) -> StageResult:
    stdout_log = job_paths.logs / f"{command.name}.stdout.log"
    stderr_log = job_paths.logs / f"{command.name}.stderr.log"

    completed = subprocess.run(
        command.command,
        cwd=command.cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    _write_stage_log(stdout_log, completed.stdout)
    _write_stage_log(stderr_log, completed.stderr)

    if completed.returncode != 0:
        raise StageExecutionError(
            stage=command.name,
            error_code=_classify_error(command, completed.stderr, completed.stdout),
            message=completed.stderr.strip() or completed.stdout.strip() or f"{command.name} failed",
        )

    artifact_paths, output_metadata = _collect_existing_artifacts(command, completed.stdout)
    output_metadata.update(
        {
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
        }
    )
    if command.progress_file and Path(command.progress_file).exists():
        output_metadata["progress_file"] = command.progress_file

    return StageResult(
        status="degraded" if output_metadata.get("stdout_json", {}).get("degraded") is True else "success",
        artifact_paths=artifact_paths,
        output_metadata=output_metadata,
    )
