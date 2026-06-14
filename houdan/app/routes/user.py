"""用户接口"""
import re
from flask import Blueprint, request
from app.response import ok, fail
from app.current_user import current_user, update_current_user

bp = Blueprint("user", __name__)

# 我的页菜单：前端 /api/user/functions 拉取后渲染
USER_FUNCS = [
    {"key": "realname", "name": "实名认证", "link": "/pages/identity/identity"},
    {"key": "fav",      "name": "我的收藏", "link": ""},
    {"key": "addr",     "name": "我的地址", "link": ""},
    {"key": "coupon",   "name": "优惠券中心", "link": ""},
]


@bp.get("/profile")
def profile():
    return ok(current_user())


@bp.get("/functions")
def functions():
    return ok(USER_FUNCS)


@bp.post("/identity")
def submit_identity():
    body = request.get_json(silent=True) or {}
    name    = (body.get("name") or "").strip()
    phone   = (body.get("phone") or "").strip()
    id_card = (body.get("id_card") or "").strip()

    if not name:
        return fail(1, "姓名不能为空")
    if not re.fullmatch(r"1\d{10}", phone):
        return fail(2, "手机号格式错误")
    if len(id_card) not in (15, 18):
        return fail(3, "身份证号格式错误")

    update_current_user({
        "real_name": name,
        "phone": phone,
        "id_card": id_card,
        "verified": True,
    })
    return ok({"verified": True}, "实名认证成功")
