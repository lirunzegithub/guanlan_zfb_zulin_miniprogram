"""异步通知日志（SQLite 持久化版）。

跨进程、跨重启都保留，多 gunicorn worker 都能写。
通过 `app.storage.repos.notify_log_repo` 落库。

仍保留 `_MAX_KEEP` 软上限：超过自动硬删最老的，避免 db 无限膨胀。
"""
from __future__ import annotations

import time
import threading
from typing import Optional

from app.storage.repos import notify_log_repo


_MAX_KEEP = 2000
_lock = threading.Lock()
_count_since_trim = 0


def record(
    channel: str,
    params: dict,
    verified: bool,
    business_ok: bool,
    duplicate: bool = False,
    note: str = "",
    raw_body: Optional[str] = None,
) -> None:
    notify_log_repo.create({
        "channel": channel,
        "verified": bool(verified),
        "business_ok": bool(business_ok),
        "duplicate": bool(duplicate),
        "note": note,
        "params": {k: v for k, v in (params or {}).items()},
        "raw_body": raw_body or "",
        "ts": int(time.time() * 1000),
    })
    _maybe_trim()


def list_recent(since_ts: int = 0, channel: str = "",
                channel_prefix: str = "", limit: int = 200) -> list[dict]:
    """按时间倒序返回；since_ts > 0 时只返回比它新的，便于前端增量轮询。

    channel        精确匹配单个通道（如 "auth_freeze"）
    channel_prefix 前缀匹配一组通道（如 "gateway:" 会匹配 gateway:xxx 全部子类型）
    """
    items = notify_log_repo.list(channel=channel) if channel else notify_log_repo.list()
    if channel_prefix:
        items = [x for x in items if str(x.get("channel") or "").startswith(channel_prefix)]
    items.sort(key=lambda x: -int(x.get("ts") or 0))
    if since_ts:
        items = [x for x in items if int(x.get("ts") or 0) > since_ts]
    return items[:limit]


def clear() -> None:
    notify_log_repo.clear()


def _maybe_trim() -> None:
    """每 100 次写检查一次软上限，超过就硬删最老的 ¼。"""
    global _count_since_trim
    with _lock:
        _count_since_trim += 1
        if _count_since_trim < 100:
            return
        _count_since_trim = 0
    total = notify_log_repo.count()
    if total <= _MAX_KEEP:
        return
    all_items = notify_log_repo.list()
    all_items.sort(key=lambda x: int(x.get("ts") or 0))  # 升序
    to_delete = all_items[: total // 4]
    for it in to_delete:
        notify_log_repo.delete(it["id"])
