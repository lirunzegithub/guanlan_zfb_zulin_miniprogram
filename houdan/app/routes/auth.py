"""小程序用户鉴权（auth_base scope）。

接口契约：
  POST /api/auth/login          body: {auth_code}    → {token, user}
  POST /api/auth/logout         需登录                 → null
  GET  /api/auth/me             需登录                 → user

实现：
  1. 前端 my.getAuthCode({scopes:['auth_base']}) 静默拿到 auth_code（不弹框）
  2. 后端 alipay.system.oauth.token 换 user_id
  3. 用 alipay user_id 做 users 表行主键 upsert
  4. 生成 24h 会话 token 返回；后续业务接口走 Authorization: Bearer <token>

  本应用未开通"获取会员基础信息"产品，所以拿不到昵称头像；前端 mine 页用
  "支付宝用户 + user_id 末 4 位" 兜底展示。
"""
from __future__ import annotations

from flask import Blueprint, request, g

from app.response import ok, fail
from app.storage.repos import user_repo
from app.alipay_client import get_client
from app import auth_user_token

bp = Blueprint("auth", __name__)


def _upsert_user(alipay_user_id: str) -> dict:
    """以支付宝 user_id 做主键 upsert；返回最新的 user dict。"""
    existed = user_repo.get(alipay_user_id)
    if existed:
        return existed
    return user_repo.create({"id": alipay_user_id})


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    auth_code = (body.get("auth_code") or "").strip()
    if not auth_code:
        return fail(40001, "缺少 auth_code")

    try:
        oauth = get_client().exchange_oauth_token(auth_code)
    except Exception as e:
        return fail(50001, f"换取 user_id 失败：{e}")

    user_id = oauth.get("user_id") or ""
    if not user_id:
        return fail(50002, "支付宝未返回 user_id")

    user = _upsert_user(user_id)
    token = auth_user_token.login(user_id)
    return ok({"token": token, "user": user}, "登录成功")


@bp.post("/logout")
def logout():
    token = getattr(g, "user_token", None)
    if token:
        auth_user_token.revoke(token)
    return ok(None, "已登出")


@bp.get("/me")
def me():
    uid = g.user_id
    u = user_repo.get(uid)
    if not u:
        return fail(404, "用户不存在")
    return ok(u)
