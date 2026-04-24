from __future__ import annotations

import asyncio
import json
import os
import platform
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from worker_app.artifacts import JobPaths
from worker_app.jobs import StageResult
from worker_app.progress import ProgressSink
from worker_app.runner import _classify_error, _collect_existing_artifacts, _write_stage_log, run_stage_command
from worker_app.stages import StageCommand, StageExecutionError


@dataclass(frozen=True)
class OpenClawSettings:
    enabled: bool = False
    gateway_url: str = "ws://host.docker.internal:18790"
    token_file: str = "/run/secrets/openclaw_gateway_token"
    agent_id: str = "main"
    collector_skill: str = "sh3rlockC/auto-koubei-collector"
    dcd_collector_skill: str = "sh3rlockC/dcd-koubei-collector"
    timeout_seconds: int = 1800
    artifact_poll_interval_seconds: float = 5.0
    stages: tuple[str, ...] = ("collecting_autohome", "collecting_dcd")
    artifact_root_container: str = "/srv/koubei/jobs"
    artifact_root_host: str | None = None

    @classmethod
    def from_env(cls) -> "OpenClawSettings":
        return cls(
            enabled=_env_bool("OPENCLAW_ADAPTER_ENABLED") or _env_bool("OPENCLAW_AUTOHOME_ENABLED"),
            gateway_url=os.getenv("OPENCLAW_GATEWAY_URL", cls.gateway_url),
            token_file=os.getenv("OPENCLAW_GATEWAY_TOKEN_FILE", cls.token_file),
            agent_id=os.getenv("OPENCLAW_AGENT_ID", cls.agent_id),
            collector_skill=os.getenv("OPENCLAW_AUTOHOME_COLLECTOR_SKILL", os.getenv("OPENCLAW_COLLECTOR_SKILL", cls.collector_skill)),
            dcd_collector_skill=os.getenv("OPENCLAW_DCD_COLLECTOR_SKILL", cls.dcd_collector_skill),
            timeout_seconds=int(os.getenv("OPENCLAW_TIMEOUT_SECONDS", os.getenv("OPENCLAW_AGENT_TIMEOUT_SECONDS", str(cls.timeout_seconds)))),
            artifact_poll_interval_seconds=float(os.getenv("OPENCLAW_ARTIFACT_POLL_INTERVAL_SECONDS", str(cls.artifact_poll_interval_seconds))),
            stages=_env_list("OPENCLAW_ADAPTER_STAGES", cls.stages),
            artifact_root_container=os.getenv("ARTIFACT_ROOT", cls.artifact_root_container),
            artifact_root_host=os.getenv("OPENCLAW_ARTIFACT_ROOT_HOST") or None,
        )

    def read_token(self) -> str | None:
        token_path = Path(self.token_file)
        if not token_path.exists():
            return None
        token = token_path.read_text(encoding="utf-8").strip()
        return token or None


class OpenClawGatewayClientProtocol(Protocol):
    def call_agent(
        self,
        message: str,
        *,
        settings: OpenClawSettings,
        session_id: str | None = None,
        stage_name: str = "openclaw",
    ) -> dict[str, Any]: ...


StageRunnerCallable = Callable[[StageCommand, JobPaths, ProgressSink], StageResult]


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    return values or default


def _command_arg(command: StageCommand, option: str) -> str:
    try:
        index = command.command.index(option)
        return command.command[index + 1]
    except (ValueError, IndexError) as exc:
        raise StageExecutionError(
            stage=command.name,
            error_code="CONFIG_ERROR",
            message=f"missing required command option: {option}",
        ) from exc


def _optional_command_arg(command: StageCommand, option: str) -> str | None:
    try:
        index = command.command.index(option)
        return command.command[index + 1]
    except (ValueError, IndexError):
        return None


def _host_path(path: str, settings: OpenClawSettings) -> str:
    if not settings.artifact_root_host:
        return path

    source_root = Path(settings.artifact_root_container).resolve()
    target_root = Path(settings.artifact_root_host).expanduser().resolve()
    candidate = Path(path).resolve()
    try:
        relative = candidate.relative_to(source_root)
    except ValueError:
        return path
    return str(target_root / relative)


def _build_autohome_message(command: StageCommand, settings: OpenClawSettings) -> str:
    series_id = _command_arg(command, "--series-id")
    output_path = _command_arg(command, "--output")
    progress_file = _command_arg(command, "--progress-file")
    validation_path = str(Path(output_path).with_suffix(".validation.json"))

    return "\n".join(
        [
            "请调用已安装或已加载的汽车之家口碑采集 skill，并严格按以下 contract 输出。",
            f"skill={settings.collector_skill}",
            f"series_id={series_id}",
            f"output_path={_host_path(output_path, settings)}",
            f"validation_json_path={_host_path(validation_path, settings)}",
            f"progress_file={_host_path(progress_file, settings)}",
            "要求：",
            "1. 采集汽车之家用户口碑，输出 Excel 到 output_path。",
            "2. 输出 validation_json_path，用于说明采集页数、记录数和校验结果。",
            "3. 按现有 progress JSON contract 写入 progress_file。",
            "4. 如果失败，明确返回失败原因；不要输出密钥、token 或其它本地凭据。",
        ]
    )


def _build_dcd_message(command: StageCommand, settings: OpenClawSettings) -> str:
    series_id = _command_arg(command, "--series-id")
    start_page = _optional_command_arg(command, "--start-page") or "1"
    output_path = _command_arg(command, "--output")
    progress_file = _command_arg(command, "--progress-file")
    validation_path = str(Path(output_path).with_suffix(".validation.json"))
    failed_pages_path = str(Path(output_path).with_suffix(".failed-pages.json"))

    return "\n".join(
        [
            "请调用已安装或已加载的懂车帝口碑采集 skill，并严格按以下 contract 输出。",
            f"skill={settings.dcd_collector_skill}",
            f"series_id={series_id}",
            f"start_page={start_page}",
            f"output_path={_host_path(output_path, settings)}",
            f"validation_json_path={_host_path(validation_path, settings)}",
            f"failed_pages_json_path={_host_path(failed_pages_path, settings)}",
            f"progress_file={_host_path(progress_file, settings)}",
            "要求：",
            "1. 采集懂车帝用户口碑，输出 Excel 到 output_path。",
            "2. 输出 validation_json_path，用于说明采集页数、记录数和校验结果。",
            "3. 如存在失败分页，输出 failed_pages_json_path；无失败分页也可以写空数组。",
            "4. 按现有 progress JSON contract 写入 progress_file。",
            "5. 如果失败，明确返回失败原因；不要输出密钥、token 或其它本地凭据。",
        ]
    )


def _build_collector_message(command: StageCommand, settings: OpenClawSettings) -> str:
    if command.name == "collecting_autohome":
        return _build_autohome_message(command, settings)
    if command.name == "collecting_dcd":
        return _build_dcd_message(command, settings)
    raise StageExecutionError(
        stage=command.name,
        error_code="CONFIG_ERROR",
        message=f"OpenClaw collector adapter does not support stage: {command.name}",
    )


def _collector_skill_for_stage(command: StageCommand, settings: OpenClawSettings) -> str:
    if command.name == "collecting_autohome":
        return settings.collector_skill
    if command.name == "collecting_dcd":
        return settings.dcd_collector_skill
    return ""


class OpenClawGatewayClient:
    def call_agent(
        self,
        message: str,
        *,
        settings: OpenClawSettings,
        session_id: str | None = None,
        stage_name: str = "openclaw",
    ) -> dict[str, Any]:
        token = settings.read_token()
        if token is None:
            raise StageExecutionError(
                stage=stage_name,
                error_code="CONFIG_ERROR",
                message=f"OpenClaw gateway token file not found: {settings.token_file}",
            )
        return asyncio.run(self._call_agent_async(message=message, settings=settings, token=token, session_id=session_id, stage_name=stage_name))

    async def _call_agent_async(
        self,
        *,
        message: str,
        settings: OpenClawSettings,
        token: str,
        session_id: str | None,
        stage_name: str,
    ) -> dict[str, Any]:
        try:
            import websockets
        except ImportError as exc:
            raise StageExecutionError(
                stage=stage_name,
                error_code="CONFIG_ERROR",
                message="Python package 'websockets' is required for OpenClaw gateway adapter",
            ) from exc

        async with websockets.connect(settings.gateway_url, max_size=25 * 1024 * 1024) as websocket:
            await self._connect(websocket, settings=settings, token=token)
            return await self._request(
                websocket,
                method="agent",
                params={
                    "message": message,
                    "agentId": settings.agent_id,
                    "sessionId": session_id,
                    "timeout": settings.timeout_seconds,
                    "idempotencyKey": str(uuid.uuid4()),
                },
                timeout_seconds=settings.timeout_seconds,
                stage_name=stage_name,
            )

    async def _connect(self, websocket, *, settings: OpenClawSettings, token: str) -> None:
        await self._wait_connect_challenge(websocket)
        await self._request(
            websocket,
            method="connect",
            params={
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "gateway-client",
                    "displayName": "vehicle-koubei-worker",
                    "version": "0.1.0",
                    "platform": platform.system().lower(),
                    "mode": "backend",
                    "instanceId": str(uuid.uuid4()),
                },
                "caps": [],
                "auth": {"token": token},
                "role": "operator",
                "scopes": ["operator.write"],
            },
            timeout_seconds=min(settings.timeout_seconds, 30),
        )

    async def _wait_connect_challenge(self, websocket) -> None:
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            frame = json.loads(raw)
            if frame.get("type") == "event" and frame.get("event") == "connect.challenge":
                return

    async def _request(
        self,
        websocket,
        *,
        method: str,
        params: dict[str, Any],
        timeout_seconds: int,
        stage_name: str = "openclaw",
        expect_final: bool = False,
    ) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        await websocket.send(json.dumps({"type": "req", "id": request_id, "method": method, "params": params}, ensure_ascii=False))
        while True:
            raw = await asyncio.wait_for(websocket.recv(), timeout=max(timeout_seconds, 1))
            frame = json.loads(raw)
            if frame.get("type") != "res" or frame.get("id") != request_id:
                continue
            if frame.get("ok") is True:
                payload = frame.get("payload") or {}
                if expect_final and payload.get("status") == "accepted":
                    continue
                return payload
            error = frame.get("error") or {}
            raise StageExecutionError(
                stage=stage_name,
                error_code=str(error.get("code") or "OPENCLAW_ERROR"),
                message=str(error.get("message") or "OpenClaw gateway request failed"),
            )


def run_collector_via_openclaw(
    command: StageCommand,
    job_paths: JobPaths,
    progress_sink: ProgressSink,
    *,
    settings: OpenClawSettings,
    gateway_client: OpenClawGatewayClientProtocol | None = None,
) -> StageResult:
    if command.name not in {"collecting_autohome", "collecting_dcd"}:
        return run_stage_command(command, job_paths, progress_sink)

    stdout_log = job_paths.logs / f"{command.name}.openclaw.stdout.log"
    stderr_log = job_paths.logs / f"{command.name}.openclaw.stderr.log"
    client = gateway_client or OpenClawGatewayClient()
    session_id = f"vehicle-koubei-{job_paths.root.name}-{command.name}"
    try:
        response = client.call_agent(
            _build_collector_message(command, settings),
            settings=settings,
            session_id=session_id,
            stage_name=command.name,
        )
    except StageExecutionError:
        raise
    except Exception as exc:
        raise StageExecutionError(
            stage=command.name,
            error_code=_classify_error(command, str(exc), ""),
            message=str(exc) or "OpenClaw collection failed",
        ) from exc

    _write_stage_log(stdout_log, json.dumps(response, ensure_ascii=False, indent=2))
    _write_stage_log(stderr_log, "")

    if response.get("status") == "accepted":
        _wait_for_expected_artifacts(command, settings)

    artifact_paths, output_metadata = _collect_existing_artifacts(command, "")
    output_metadata.update(
        {
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "openclaw_gateway_url": settings.gateway_url,
            "openclaw_agent_id": settings.agent_id,
            "openclaw_skill": _collector_skill_for_stage(command, settings),
        }
    )
    if command.progress_file and Path(command.progress_file).exists():
        output_metadata["progress_file"] = command.progress_file

    return StageResult(status="success", artifact_paths=artifact_paths, output_metadata=output_metadata)


def run_autohome_via_openclaw(
    command: StageCommand,
    job_paths: JobPaths,
    progress_sink: ProgressSink,
    *,
    settings: OpenClawSettings,
    gateway_client: OpenClawGatewayClientProtocol | None = None,
) -> StageResult:
    return run_collector_via_openclaw(
        command,
        job_paths,
        progress_sink,
        settings=settings,
        gateway_client=gateway_client,
    )


def _wait_for_expected_artifacts(command: StageCommand, settings: OpenClawSettings) -> None:
    deadline = time.monotonic() + max(settings.timeout_seconds, 1)
    while True:
        missing = [artifact for artifact in command.expected_artifacts if not Path(artifact).exists()]
        if not missing:
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise StageExecutionError(
                stage=command.name,
                error_code="TIMEOUT",
                message=f"OpenClaw did not produce expected artifacts within {settings.timeout_seconds} seconds: {', '.join(missing)}",
            )

        time.sleep(min(settings.artifact_poll_interval_seconds, remaining))


def build_stage_runner(
    *,
    settings: OpenClawSettings | None = None,
    direct_runner: StageRunnerCallable = run_stage_command,
) -> StageRunnerCallable:
    settings = settings or OpenClawSettings.from_env()
    enabled_stages = set(settings.stages)

    def runner(command: StageCommand, job_paths: JobPaths, progress_sink: ProgressSink) -> StageResult:
        # OpenClaw is a per-stage adapter. The worker remains the pipeline owner
        # and keeps local execution for every stage not explicitly routed here.
        if settings.enabled and command.name in enabled_stages:
            if command.name in {"collecting_autohome", "collecting_dcd"}:
                return run_collector_via_openclaw(command, job_paths, progress_sink, settings=settings)
        return direct_runner(command, job_paths, progress_sink)

    return runner
