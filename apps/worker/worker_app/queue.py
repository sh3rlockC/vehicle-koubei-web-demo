from __future__ import annotations

from redis import Redis
from rq import Queue


def make_redis_connection(redis_url: str) -> Redis:
    return Redis.from_url(redis_url)


def make_queue(redis_url: str, name: str = "vehicle-koubei") -> Queue:
    return Queue(name=name, connection=make_redis_connection(redis_url))
