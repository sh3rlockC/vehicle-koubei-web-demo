from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import worker_jobs
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


def test_wordcloud_stage_uses_container_cjk_font_path(tmp_path: Path) -> None:
    job_paths = ensure_job_dirs(tmp_path / "jobs", "job_font")
    dependency_map = {
        "auto-koubei-collector": {"path": str(tmp_path), "entrypoint": "auto.py"},
        "dcd-koubei-collector": {"path": str(tmp_path), "entrypoint": "dcd.py"},
        "koubei-postprocess": {"path": str(tmp_path), "entrypoint": "post.py"},
        "koubei-keyword-summary-skill": {"path": str(tmp_path), "entrypoint": "summary.py"},
        "koubei-wordcloud": {"path": str(tmp_path), "entrypoint": "wordcloud.py"},
    }

    stages = build_stage_commands(
        job_paths=job_paths,
        model_name="测试车",
        autohome_series_id="8089",
        dongchedi_series_id="25398",
        dependency_map=dependency_map,
    )

    wordcloud_stage = next(stage for stage in stages if stage.name == "rendering_wordcloud")
    assert "--font-path" in wordcloud_stage.command
    font_path = wordcloud_stage.command[wordcloud_stage.command.index("--font-path") + 1]
    assert font_path == "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
