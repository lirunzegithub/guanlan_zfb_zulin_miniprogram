"""管理后台 Session Token：进程内 dict 实现。

特点：
- Token = 64 hex chars（random，不可猜）
- TTL 由 AdminConfig.SESSION_HOURS 控制
- 进程重启即失效（用户需重新登录，但工作人员账号本身在 DB 里不变）

生产建议换 Redis 或写表，保留同接口（login/get/refresh/revoke）即可无缝替换。
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Optional

from app.config import AdminConfig

_lock = threading.Lock()
_sessions: dict[str, dict] = {}   # token -> {staff_id, created_at, expires_at}


def _now() -> int:
    return int(time.time())


def login(staff_id: int) -> str:
    """生成新 token，返回字符串。"""
    token = secrets.token_hex(32)
    with _lock:
        _sessions[token] = {
            "staff_id": staff_id,
            "created_at": _now(),
            "expires_at": _now() + AdminConfig.SESSION_HOURS * 3600,
        }
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
            return None
    return s


def refresh(token: str) -> bool:
    with _lock:
        s = _sessions.get(token)
        if not s or s["expires_at"] < _now():
            return False
        s["expires_at"] = _now() + AdminConfig.SESSION_HOURS * 3600
        return True


def revoke(token: str) -> None:
    with _lock:
        _sessions.pop(token, None)


def revoke_all_for_staff(staff_id: int) -> int:
    """改密时主动注销该用户所有 token。"""
    n = 0
    with _lock:
        for t in list(_sessions.keys()):
            if _sessions[t]["staff_id"] == staff_id:
                _sessions.pop(t, None)
                n += 1
    return n
