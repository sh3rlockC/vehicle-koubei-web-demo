from __future__ import annotations

import os

from rq import Worker

from worker_app.cleanup import cleanup_settings_from_env, start_cleanup_thread
from worker_app.queue import make_redis_connection


def main() -> int:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    queue_name = os.getenv("WORKER_QUEUE_NAME", "vehicle-koubei")
    database_url = os.getenv("DATABASE_URL", "sqlite+pysqlite:///./vehicle_koubei.db")
    artifact_root = os.getenv("ARTIFACT_ROOT", "/srv/koubei/jobs")
    cleanup_settings = cleanup_settings_from_env()
    connection = make_redis_connection(redis_url)
    start_cleanup_thread(database_url=database_url, artifact_root=artifact_root, settings=cleanup_settings)
    print(
        f"cleanup ready: retention={cleanup_settings.retention_days}d interval={cleanup_settings.interval_seconds}s",
        flush=True,
    )
    worker = Worker(queues=[queue_name], connection=connection)
    print(f"worker queue ready: {queue_name}")
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
