"""收货地址：CRUD + 设默认

接口契约：
  GET    /api/user/addresses              当前用户的地址列表（默认排前）
  GET    /api/user/addresses/<id>         单条
  POST   /api/user/addresses              新增；body 含 receiver_name / phone / province / city / district / detail / zip_code? / is_default? / source?
  PUT    /api/user/addresses/<id>         更新
  DELETE /api/user/addresses/<id>         软删除
  POST   /api/user/addresses/<id>/default 设为默认（自动把其他地址 is_default 置 false）
"""
import re
from flask import Blueprint, request
from app.response import ok, fail
from app.storage.repos import address_repo
from app.current_user import current_user_id as _current_user_id

bp = Blueprint("addresses", __name__)

_REQUIRED = ("receiver_name", "receiver_phone", "province", "city", "district", "detail")


def _validate(body: dict) -> str | None:
    for k in _REQUIRED:
        if not (body.get(k) or "").strip():
            return f"{k} 必填"
    if not re.fullmatch(r"1\d{10}", body.get("receiver_phone", "")):
        return "手机号格式错误"
    return None


def _sort_default_first(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda x: (not x.get("is_default"), -int(x.get("updated_at") or 0)))


@bp.get("")
def list_addr():
    uid = _current_user_id()
    items = address_repo.list(user_id=uid)
    return ok({"list": _sort_default_first(items), "total": len(items)})


@bp.get("/<int:aid>")
def get_addr(aid):
    a = address_repo.get(aid)
    if not a or a.get("user_id") != _current_user_id():
        return fail(404, "地址不存在")
    return ok(a)


@bp.post("")
def create_addr():
    body = request.get_json(silent=True) or {}
    err = _validate(body)
    if err:
        return fail(1, err)

    uid = _current_user_id()
    # 第一个地址自动设默认
    no_addr_yet = not address_repo.list(user_id=uid)
    make_default = bool(body.get("is_default")) or no_addr_yet

    record = {
        "user_id": uid,
        "receiver_name":  body["receiver_name"].strip(),
        "receiver_phone": body["receiver_phone"].strip(),
        "province":       body["province"].strip(),
        "city":           body["city"].strip(),
        "district":       body["district"].strip(),
        "detail":         body["detail"].strip(),
        "zip_code":       (body.get("zip_code") or "").strip(),
        "source":         body.get("source") if body.get("source") in ("manual", "alipay") else "manual",
        "is_default":     make_default,
    }
    created = address_repo.create(record)
    if make_default:
        _clear_other_defaults(uid, created["id"])
    return ok(created, "已添加")


@bp.put("/<int:aid>")
def update_addr(aid):
    a = address_repo.get(aid)
    if not a or a.get("user_id") != _current_user_id():
        return fail(404, "地址不存在")
    body = request.get_json(silent=True) or {}
    err = _validate({**a, **body})
    if err:
        return fail(1, err)
    fields = {k: body[k].strip() if isinstance(body.get(k), str) else body[k]
              for k in _REQUIRED + ("zip_code", "source") if k in body}
    if "is_default" in body:
        fields["is_default"] = bool(body["is_default"])
    updated = address_repo.update(aid, fields)
    if fields.get("is_default"):
        _clear_other_defaults(a["user_id"], aid)
    return ok(updated, "已更新")


@bp.delete("/<int:aid>")
def delete_addr(aid):
    a = address_repo.get(aid)
    if not a or a.get("user_id") != _current_user_id():
        return fail(404, "地址不存在")
    address_repo.delete(aid)
    # 若删的是默认地址，剩余里第一个升为默认
    if a.get("is_default"):
        rest = address_repo.list(user_id=a["user_id"])
        rest = _sort_default_first(rest)
        if rest:
            address_repo.update(rest[0]["id"], {"is_default": True})
    return ok(None, "已删除")


@bp.post("/<int:aid>/default")
def set_default(aid):
    a = address_repo.get(aid)
    if not a or a.get("user_id") != _current_user_id():
        return fail(404, "地址不存在")
    address_repo.update(aid, {"is_default": True})
    _clear_other_defaults(a["user_id"], aid)
    return ok(None, "已设为默认")


# ---------- internal ----------
def _clear_other_defaults(uid: str, keep_id: int) -> None:
    for it in address_repo.list(user_id=uid, is_default=True):
        if it["id"] != keep_id:
            address_repo.update(it["id"], {"is_default": False})
