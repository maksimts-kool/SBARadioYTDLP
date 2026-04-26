from __future__ import annotations

from typing import Optional

from .models import JobStatusResponse


class RedisJobStore:
    def __init__(
        self,
        redis_url: str | None,
        namespace: str = "sbaradio-ytdlp",
        lock_ttl_seconds: int = 6 * 60 * 60,
        socket_timeout_seconds: float = 1.0,
    ) -> None:
        self.redis_url = (redis_url or "").strip()
        self.namespace = namespace.strip() or "sbaradio-ytdlp"
        self.lock_ttl_seconds = lock_ttl_seconds
        self.socket_timeout_seconds = socket_timeout_seconds
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.redis_url)

    def reserve_active_slot(self, job_id: str, max_active_jobs: int) -> bool:
        if not self.enabled:
            return True

        script = """
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - ARGV[2])
        if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
          return 0
        end
        redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
        redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
        return 1
        """
        now = self._now_seconds()
        result = self._client_or_raise().eval(
            script,
            2,
            self._active_index_key(),
            self._active_job_key(job_id),
            now,
            self.lock_ttl_seconds,
            max_active_jobs,
            job_id,
        )
        return result == 1

    def refresh_active_slot(self, job_id: str) -> None:
        if not self.enabled:
            return

        client = self._client_or_raise()
        now = self._now_seconds()
        with client.pipeline() as pipe:
            pipe.zadd(self._active_index_key(), {job_id: now})
            pipe.set(self._active_job_key(job_id), "1", ex=self.lock_ttl_seconds)
            pipe.execute()

    def release_active_slot(self, job_id: str) -> None:
        if not self.enabled:
            return

        client = self._client_or_raise()
        with client.pipeline() as pipe:
            pipe.zrem(self._active_index_key(), job_id)
            pipe.delete(self._active_job_key(job_id))
            pipe.execute()

    def remember_job(self, snapshot: JobStatusResponse, history_limit: int) -> None:
        if not self.enabled:
            return

        client = self._client_or_raise()
        job_id = snapshot.jobId
        score = snapshot.updatedAt.timestamp()
        history_key = self._history_key()
        snapshot_key = self._snapshot_key(job_id)

        with client.pipeline() as pipe:
            pipe.set(snapshot_key, snapshot.model_dump_json())
            pipe.zadd(history_key, {job_id: score})
            pipe.zcard(history_key)
            results = pipe.execute()

        count = int(results[-1])
        if count <= history_limit:
            return

        overflow = count - history_limit
        stale_ids = client.zrange(history_key, 0, overflow - 1)
        stale_job_ids = [self._decode(value) for value in stale_ids]
        with client.pipeline() as pipe:
            for stale_job_id in stale_job_ids:
                pipe.zrem(history_key, stale_job_id)
                pipe.delete(self._snapshot_key(stale_job_id))
            pipe.execute()

    def load_history(self, history_limit: int) -> list[JobStatusResponse]:
        if not self.enabled:
            return []

        client = self._client_or_raise()
        job_ids = [self._decode(value) for value in client.zrevrange(self._history_key(), 0, history_limit - 1)]
        snapshots: list[JobStatusResponse] = []
        for payload in client.mget([self._snapshot_key(job_id) for job_id in job_ids]):
            if not payload:
                continue
            try:
                snapshots.append(JobStatusResponse.model_validate_json(self._decode(payload)))
            except ValueError:
                continue
        return snapshots

    def _client_or_raise(self):
        if self._client is not None:
            return self._client

        import redis

        self._client = redis.Redis.from_url(
            self.redis_url,
            socket_connect_timeout=self.socket_timeout_seconds,
            socket_timeout=self.socket_timeout_seconds,
        )
        return self._client

    def _active_index_key(self) -> str:
        return f"{self.namespace}:jobs:active"

    def _active_job_key(self, job_id: str) -> str:
        return f"{self.namespace}:jobs:active:{job_id}"

    def _history_key(self) -> str:
        return f"{self.namespace}:jobs:history"

    def _snapshot_key(self, job_id: str) -> str:
        return f"{self.namespace}:jobs:snapshot:{job_id}"

    @staticmethod
    def _now_seconds() -> int:
        import time

        return int(time.time())

    @staticmethod
    def _decode(value: str | bytes | bytearray | memoryview) -> str:
        if isinstance(value, str):
            return value
        return bytes(value).decode("utf-8")


class NullRedisJobStore(RedisJobStore):
    def __init__(self) -> None:
        super().__init__(None)


OptionalRedisJobStore = Optional[RedisJobStore]
