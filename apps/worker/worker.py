from __future__ import annotations

import os

from rq import Worker

from worker_app.queue import make_redis_connection


def main() -> int:
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    queue_name = os.getenv("WORKER_QUEUE_NAME", "vehicle-koubei")
    connection = make_redis_connection(redis_url)
    worker = Worker(queues=[queue_name], connection=connection)
    print(f"worker queue ready: {queue_name}")
    worker.work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
