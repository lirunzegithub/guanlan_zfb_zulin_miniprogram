"""当前登录用户的统一入口。

数据来源：app/__init__.py 的 `_auth_guard` 中间件，验签通过后把
user_id 写到 Flask `g.user_id`。

调用约定：
- `current_user_id()` 必须在登录保护路由里调用，未登录会抛 RuntimeError
  （正常请求走不到，会被中间件提前 401）；
- `current_user()` 返回 users 表行；缺失时给一个最小占位 dict（避免
  老代码 `.get` 时 NPE）。
"""
from __future__ import annotations

from typing import Optional

from flask import g, has_request_context

from app.storage.repos import user_repo


def current_user_id() -> str:
    if not has_request_context():
        raise RuntimeError("current_user_id() 必须在请求上下文里调用")
    uid = getattr(g, "user_id", None)
    if not uid:
        raise RuntimeError("current_user_id() 调用时未登录（请检查路由是否在公开白名单里）")
    return uid


def current_user() -> dict:
    uid = current_user_id()
    return user_repo.get(uid) or {"id": uid}


def update_current_user(data: dict) -> Optional[dict]:
    return user_repo.update(current_user_id(), data)
