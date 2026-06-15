from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Iterator

try:
    from redis import Redis
    from redis.exceptions import RedisError
except ImportError:  # Redis is optional when REDIS_URL is empty.
    Redis = None  # type: ignore[assignment]

    class RedisError(Exception):
        pass

from app.config import get_settings

logger = logging.getLogger(__name__)
_client: Redis | None = None  # type: ignore[valid-type]
_warned_unavailable = False


@dataclass(slots=True)
class RedisLock:
    key: str
    token: str
    ttl_seconds: int
    acquired: bool = False

    def release(self) -> None:
        client = get_redis_client()
        if not client or not self.acquired:
            return
        try:
            # Delete only the lock owned by this process. This avoids deleting a newer lock
            # if the current lock expired and another worker acquired it.
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
            """
            client.eval(script, 1, self.key, self.token)
        except RedisError:
            logger.debug("Redis lock release failed for %s", self.key, exc_info=True)
        finally:
            self.acquired = False

    def __enter__(self) -> "RedisLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def redis_configured() -> bool:
    settings = get_settings()
    return bool(settings.redis_enabled and settings.redis_url)


def get_redis_client() -> Redis | None:
    global _client, _warned_unavailable
    settings = get_settings()
    if not redis_configured():
        return None
    if Redis is None:
        if not _warned_unavailable:
            logger.warning("redis package is not installed; falling back to database-only mode")
            _warned_unavailable = True
        return None
    if _client is None:
        try:
            _client = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=settings.redis_socket_timeout_seconds,
                socket_connect_timeout=settings.redis_socket_timeout_seconds,
                health_check_interval=30,
            )
        except Exception:
            if not _warned_unavailable:
                logger.warning("Redis client could not be created; falling back to database-only mode", exc_info=True)
                _warned_unavailable = True
            _client = None
    return _client


def redis_ping() -> bool:
    client = get_redis_client()
    if not client:
        return False
    try:
        return bool(client.ping())
    except RedisError:
        logger.debug("Redis ping failed", exc_info=True)
        return False


def close_redis() -> None:
    global _client
    if not _client:
        return
    try:
        _client.close()
    except RedisError:
        logger.debug("Redis close failed", exc_info=True)
    finally:
        _client = None


def acquire_redis_lock(key: str, ttl_seconds: int = 30) -> RedisLock | None:
    client = get_redis_client()
    if not client:
        return None
    ttl = max(1, int(ttl_seconds))
    token = secrets.token_urlsafe(24)
    lock = RedisLock(key=key, token=token, ttl_seconds=ttl)
    try:
        lock.acquired = bool(client.set(key, token, nx=True, ex=ttl))
        return lock
    except RedisError:
        logger.debug("Redis lock acquire failed for %s", key, exc_info=True)
        return None


def redis_rate_limited(key: str, seconds: int) -> tuple[bool, int] | None:
    """Return (limited, seconds_left), or None when Redis is disabled/unavailable."""
    client = get_redis_client()
    if not client:
        return None
    ttl = max(1, int(seconds))
    try:
        allowed = bool(client.set(key, "1", nx=True, ex=ttl))
        if allowed:
            return False, 0
        left = client.ttl(key)
        if left is None or left < 1:
            left = 1
        return True, int(left)
    except RedisError:
        logger.debug("Redis rate limit failed for %s", key, exc_info=True)
        return None
