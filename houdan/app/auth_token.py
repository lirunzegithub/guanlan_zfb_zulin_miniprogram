"""管理后台 Session Token（落盘持久化 + TTL）。

跟 auth_user_token.py（小程序用户用）同形，但完全独立的命名空间。
- Token = 64 hex chars（random，不可猜）
- TTL 由 AdminConfig.SESSION_HOURS 控制
- 持久化到 data/admin_sessions.json：后端重启（部署新代码）后员工老 token
  仍然有效，不会被踢回登录页。历史上这里是纯内存 dict，每次部署全员掉线。

生产建议换 Redis / DB，保持同接口（login/get/refresh/revoke）即可无缝替换。
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from app.config import AdminConfig

_lock = threading.Lock()
_sessions: dict[str, dict] = {}   # token -> {staff_id, created_at, expires_at}

_STORE_PATH = Path(__file__).resolve().parent.parent / "data" / "admin_sessions.json"


def _now() -> int:
    return int(time.time())


def _load() -> None:
    """启动时从磁盘加载未过期的 session 到内存。"""
    if not _STORE_PATH.exists():
        return
    try:
        raw = _STORE_PATH.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return
    now = _now()
    for token, s in (data or {}).items():
        try:
            if int(s.get("expires_at") or 0) > now and s.get("staff_id") is not None:
                _sessions[token] = {
                    "staff_id":   int(s["staff_id"]),
                    "created_at": int(s.get("created_at") or now),
                    "expires_at": int(s["expires_at"]),
                }
        except Exception:
            continue


def _flush_locked() -> None:
    """把内存里的 _sessions 原子写到磁盘。调用方必须持有 _lock。"""
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".admin_sessions.", suffix=".tmp", dir=str(_STORE_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_sessions, f, ensure_ascii=False)
        os.replace(tmp_path, _STORE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def login(staff_id: int) -> str:
    """生成新 token，返回字符串。"""
    token = secrets.token_hex(32)
    with _lock:
        _sessions[token] = {
            "staff_id": int(staff_id),
            "created_at": _now(),
            "expires_at": _now() + AdminConfig.SESSION_HOURS * 3600,
        }
        _flush_locked()
    return token


def get(token: str) -> Optional[dict]:
    """校验 token；返回 session dict，失败/过期返回 None。"""
    if not token:
        return None
    with _lock:
        s = _sessions.get(token)
        if not s:
            return None
        if s["expires_at"] < _now():
            _sessions.pop(token, None)
            _flush_locked()
            return None
    return s


def refresh(token: str) -> bool:
    with _lock:
        s = _sessions.get(token)
        if not s or s["expires_at"] < _now():
            return False
        s["expires_at"] = _now() + AdminConfig.SESSION_HOURS * 3600
        _flush_locked()
        return True


def revoke(token: str) -> None:
    with _lock:
        if _sessions.pop(token, None) is not None:
            _flush_locked()


def revoke_all_for_staff(staff_id: int) -> int:
    """改密时主动注销该用户所有 token。"""
    n = 0
    with _lock:
        for t in list(_sessions.keys()):
            if _sessions[t]["staff_id"] == staff_id:
                _sessions.pop(t, None)
                n += 1
        if n:
            _flush_locked()
    return n


# 模块导入即加载磁盘缓存
_load()
