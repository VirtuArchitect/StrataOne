from strataone.queue import RedisJobQueue
from strataone.store import _postgres_sql


class FakeRedis:
    def __init__(self) -> None:
        self.values = []

    def rpush(self, key, value) -> None:
        self.values.append((key, value))

    def lpop(self, key):
        for index, (item_key, value) in enumerate(self.values):
            if item_key == key:
                self.values.pop(index)
                return value.encode("utf-8")
        return None


def test_redis_queue_enqueues_and_dequeues_job_ids() -> None:
    queue = RedisJobQueue(key="test:jobs", client=FakeRedis())

    queue.enqueue("job-123")

    assert queue.dequeue() == "job-123"
    assert queue.dequeue() is None


def test_postgres_sql_placeholder_conversion() -> None:
    assert _postgres_sql("SELECT * FROM jobs WHERE id = ? AND status = ?") == "SELECT * FROM jobs WHERE id = %s AND status = %s"
