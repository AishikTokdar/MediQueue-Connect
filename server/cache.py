import json
import time
import threading
from typing import Any, Dict, Optional

try:
    import redis
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class CacheManager:

    def __init__(self, host: str = "127.0.0.1", port: int = 6379, db: int = 0):
        self.use_redis = False
        self.client = None
        self._lock = threading.Lock()
        self._memory_store: Dict[str, Any] = {}
        self._memory_expiry: Dict[str, float] = {}

        if _REDIS_AVAILABLE:
            try:
                r = redis.Redis(host=host, port=port, db=db, socket_timeout=0.5, socket_connect_timeout=0.5)
                r.ping()
                self.client = r
                self.use_redis = True
            except Exception:
                self.use_redis = False

    # Session Cache
    def set_session(self, token: str, user: str, ttl: int = 3600) -> None:
        key = f"session:{token}"
        if self.use_redis and self.client:
            try:
                self.client.setex(key, ttl, user)
                return
            except Exception:
                self.use_redis = False

        with self._lock:
            self._memory_store[key] = user
            self._memory_expiry[key] = time.time() + ttl

    def get_session(self, token: str) -> Optional[str]:
        key = f"session:{token}"
        if self.use_redis and self.client:
            try:
                val = self.client.get(key)
                if val:
                    return val.decode("utf-8") if isinstance(val, bytes) else str(val)
                return None
            except Exception:
                self.use_redis = False

        with self._lock:
            if key in self._memory_store:
                if time.time() < self._memory_expiry.get(key, 0):
                    return self._memory_store[key]
                else:
                    del self._memory_store[key]
                    del self._memory_expiry[key]
            return None

    def delete_session(self, token: str) -> None:
        key = f"session:{token}"
        if self.use_redis and self.client:
            try:
                self.client.delete(key)
                return
            except Exception:
                self.use_redis = False

        with self._lock:
            self._memory_store.pop(key, None)
            self._memory_expiry.pop(key, None)

    # Doctor Slots Cache
    def get_slots_cache(self, key: str) -> Optional[Dict[str, Any]]:
        full_key = f"slots_cache:{key}"
        if self.use_redis and self.client:
            try:
                val = self.client.get(full_key)
                if val:
                    return json.loads(val.decode("utf-8") if isinstance(val, bytes) else str(val))
                return None
            except Exception:
                self.use_redis = False

        with self._lock:
            if full_key in self._memory_store:
                if time.time() < self._memory_expiry.get(full_key, 0):
                    return self._memory_store[full_key]
                else:
                    del self._memory_store[full_key]
                    del self._memory_expiry[full_key]
            return None

    def set_slots_cache(self, key: str, data: Dict[str, Any], ttl: int = 60) -> None:
        full_key = f"slots_cache:{key}"
        if self.use_redis and self.client:
            try:
                self.client.setex(full_key, ttl, json.dumps(data))
                return
            except Exception:
                self.use_redis = False

        with self._lock:
            self._memory_store[full_key] = data
            self._memory_expiry[full_key] = time.time() + ttl

    def invalidate_slots_cache(self) -> None:
        if self.use_redis and self.client:
            try:
                keys = self.client.keys("slots_cache:*")
                if keys:
                    self.client.delete(*keys)
                return
            except Exception:
                self.use_redis = False

        with self._lock:
            keys_to_del = [k for k in self._memory_store if k.startswith("slots_cache:")]
            for k in keys_to_del:
                self._memory_store.pop(k, None)
                self._memory_expiry.pop(k, None)
