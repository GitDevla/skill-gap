import json
from datetime import UTC, datetime

import redis

import config


def analysis_key(person_id: int | str, occupation_id: str) -> str:
    return f"person:{person_id}:occupation:{occupation_id}:analysis"


class RedisStore:
    def __init__(self, url: str = config.REDIS_URL, ttl_seconds: int = config.ANALYSIS_CACHE_TTL_SECONDS):
        self.redis = redis.Redis.from_url(url, decode_responses=True)
        self.ttl_seconds = ttl_seconds

    def clear_all_analyses(self) -> None:
        self.redis.flushdb()

    def fetch_cached_analysis(self, person_id: int, occupation_id: str) -> dict | None:
        cached_json = self.redis.get(analysis_key(person_id, occupation_id))

        if cached_json is None:
            return None
        return json.loads(cached_json)

    def set_cached_analysis(self, person_id: int, occupation_id: str, analysis: dict) -> None:
        cache_entry = analysis | {"refreshed_at": datetime.now(UTC).isoformat()}
        analysis_json = json.dumps(cache_entry, default=str)
        self.redis.set(analysis_key(person_id, occupation_id), analysis_json, ex=self.ttl_seconds)

    def delete_person_cached_analyses(self, person_id: int) -> int:
        return self._delete_matching_keys(analysis_key(person_id, "*"))

    def delete_occupation_cached_analyses(self, occupation_id: str) -> int:
        return self._delete_matching_keys(analysis_key("*", occupation_id))

    def _delete_matching_keys(self, key_pattern: str) -> int:
        matching_keys = list(self.redis.scan_iter(key_pattern))

        if not matching_keys:
            return 0
        return self.redis.delete(*matching_keys)

    def fetch_cached_analyses_page(self, limit: int, offset: int) -> tuple[list[dict], int]:
        cached_keys = sorted(self.redis.scan_iter(analysis_key("*", "*")))
        page_keys = cached_keys[offset : offset + limit]
        transaction = self.redis.pipeline(transaction=True)
        for key in page_keys:
            transaction.get(key)
            transaction.ttl(key)
        replies = transaction.execute()

        cache_entries = []
        for i, key in enumerate(page_keys):
            cached = json.loads(replies[2 * i]) if replies[2 * i] else None
            cache_entries.append({"key": key, "ttl_seconds": replies[2 * i + 1], "value": cached})
        return cache_entries, len(cached_keys)
