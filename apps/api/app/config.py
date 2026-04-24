from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def discover_workspace_root(
    source_path: Path | None = None,
    *,
    mounted_workspace: Path | None = None,
    fallback_cwd: Path | None = None,
) -> Path:
    workspace_mount = (mounted_workspace or Path("/workspace")).expanduser()
    if workspace_mount.exists():
        return workspace_mount.resolve()

    file_path = (source_path or Path(__file__)).resolve()
    for parent in file_path.parents:
        if (parent / "config" / "dependencies.yaml").exists():
            return parent.parent.resolve()

    return (fallback_cwd or Path.cwd()).expanduser().resolve()


class Settings(BaseSettings):
    app_env: str = "development"
    base_url: str = "http://localhost"
    database_url: str = "sqlite+pysqlite:///./vehicle_koubei.db"
    redis_url: str = "redis://redis:6379/0"
    worker_queue_name: str = "vehicle-koubei"
    worker_job_timeout_seconds: int = 3600
    artifact_root: str = "/srv/koubei/jobs"
    workspace_root: str = str(discover_workspace_root())

    pass_phrase_hash: str = ""
    pass_phrase_version: str = "2026-W17"
    session_secret: str = "change-me"
    session_cookie_name: str = "koubei_access"
    session_ttl_seconds: int = 4 * 60 * 60

    llm_provider: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model_report: str = ""
    llm_model_qa: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def artifact_root_path(self) -> Path:
        return Path(self.artifact_root).expanduser().resolve()

    @property
    def workspace_root_path(self) -> Path:
        return Path(self.workspace_root).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
