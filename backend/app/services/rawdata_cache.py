"""原始数据页统计/筛选项的进程内短 TTL 缓存。

统计接口在无筛选时会扫描千万级 raw_data；这里缓存相同条件的统计结果和总数，
并用单飞锁避免多个请求同时触发同一份全表扫描。上传/删除原始数据时显式失效。
"""
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Hashable

FILTERS_TTL_SECONDS = 600.0
STATS_TTL_SECONDS = 300.0
COUNT_TTL_SECONDS = 300.0

# 测试环境不启用，避免跨用例污染
_enabled = "pytest" not in sys.modules
_cache: dict[tuple[str, Hashable], tuple[float, Any]] = {}
_locks: dict[tuple[str, Hashable], threading.Lock] = {}
_guard = threading.Lock()
_generation = 0


def invalidate_rawdata_cache() -> None:
    global _generation
    with _guard:
        _cache.clear()
        _generation += 1


def _get(namespace: str, key: Hashable, ttl: float) -> Any | None:
    if not _enabled:
        return None
    with _guard:
        entry = _cache.get((namespace, key))
        if entry is None:
            return None
        cached_at, value = entry
        if time.monotonic() - cached_at > ttl:
            _cache.pop((namespace, key), None)
            return None
        return value


def _set(namespace: str, key: Hashable, value: Any, generation: int) -> None:
    if not _enabled:
        return
    with _guard:
        if _generation != generation:
            return
        if len(_cache) >= 512:
            _cache.clear()
            _locks.clear()
        _cache[(namespace, key)] = (time.monotonic(), value)


def _lock_for(namespace: str, key: Hashable) -> threading.Lock:
    with _guard:
        return _locks.setdefault((namespace, key), threading.Lock())


def cached_value(namespace: str, key: Hashable, ttl: float, loader: Callable[[], Any]) -> Any:
    """按 key 缓存 loader 结果；同一 key 并发时只执行一次 loader。"""
    if not _enabled:
        return loader()

    cached = _get(namespace, key, ttl)
    if cached is not None:
        return cached

    lock = _lock_for(namespace, key)
    with lock:
        cached = _get(namespace, key, ttl)
        if cached is not None:
            return cached
        with _guard:
            generation = _generation
        value = loader()
        _set(namespace, key, value, generation)
        return value
