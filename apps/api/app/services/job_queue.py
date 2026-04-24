from __future__ import annotations

from fastapi import Depends
from redis import Redis
from rq import Queue

from app.config import Settings, get_settings


def make_redis_connection(redis_url: str) -> Redis:
    return Redis.from_url(redis_url)


def get_job_queue(settings: Settings = Depends(get_settings)) -> Queue:
    return Queue(name=settings.worker_queue_name, connection=make_redis_connection(settings.redis_url))
