import os
from typing import Protocol


class JobQueue(Protocol):
    def enqueue(self, job_id: str) -> None:
        ...

    def dequeue(self) -> str | None:
        ...


class RedisJobQueue:
    def __init__(self, url: str | None = None, key: str | None = None, client=None) -> None:
        self.key = key or os.getenv("STRATAONE_REDIS_QUEUE_KEY", "strataone:jobs")
        if client is not None:
            self.client = client
            return
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("Redis queue backend requires the redis package") from exc
        self.client = redis.Redis.from_url(url or os.getenv("STRATAONE_REDIS_URL", "redis://redis:6379/0"))

    def enqueue(self, job_id: str) -> None:
        self.client.rpush(self.key, job_id)

    def dequeue(self) -> str | None:
        value = self.client.lpop(self.key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)


def queue_backend() -> str:
    return os.getenv("STRATAONE_QUEUE_BACKEND", "database").lower()


def get_job_queue() -> JobQueue | None:
    if queue_backend() == "redis":
        return RedisJobQueue()
    return None
