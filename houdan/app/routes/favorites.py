"""我的收藏：列表 / 切换 / 删除。

接口契约：
  GET    /api/user/favorites?page=1&size=20      → 列表（商品卡形态）+ total
  POST   /api/user/favorites                     body: {product_id}           → 新增（已收藏则幂等返回）
  DELETE /api/user/favorites/<pid>                                            → 取消
  POST   /api/user/favorites/<pid>/toggle                                     → 切换，返回当前收藏状态

存储：favorite_repo（user_id + product_id 复合），同一用户对同一商品仅一条。
"""
from __future__ import annotations

from flask import Blueprint, request

from app.response import ok, fail
from app.storage.repos import favorite_repo, product_repo
from app.current_user import current_user_id
from app.routes.products import _to_card

bp = Blueprint("favorites", __name__)


def _find_fav(user_id: str, pid: int) -> dict | None:
    return favorite_repo.find(user_id=user_id, product_id=pid)


def _coerce_pid(raw) -> int | None:
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


@bp.get("")
def list_favorites():
    uid = current_user_id()
    page = max(request.args.get("page", default=1, type=int), 1)
    size = min(request.args.get("size", default=20, type=int), 100)

    favs = favorite_repo.list(user_id=uid)
    # 新收藏的排在前
    favs.sort(key=lambda x: -int(x.get("created_at") or 0))

    total = len(favs)
    sliced = favs[(page - 1) * size: (page - 1) * size + size]

    cards = []
    stale_ids: list = []
    for f in sliced:
        p = product_repo.get(f.get("product_id"))
        if not p or p.get("status") != "on":
            # 商品已下架/删除：跳过，并顺手清掉这条收藏（避免列表里一直有"空位"）
            stale_ids.append(f["id"])
            continue
        card = _to_card(p)
        card["fav_id"] = f["id"]
        card["favorited_at"] = int(f.get("created_at") or 0)
        cards.append(card)

    for fid in stale_ids:
        favorite_repo.delete(fid)

    return ok({
        "list": cards,
        "total": total - len(stale_ids),
        "page": page,
        "size": size,
    })


@bp.post("")
def add_favorite():
    body = request.get_json(silent=True) or {}
    pid = _coerce_pid(body.get("product_id"))
    if not pid:
        return fail(1, "product_id 非法")
    if not product_repo.get(pid):
        return fail(404, "商品不存在")

    uid = current_user_id()
    existed = _find_fav(uid, pid)
    if existed:
        return ok({"favorited": True, "fav_id": existed["id"]}, "已在收藏中")

    rec = favorite_repo.create({"user_id": uid, "product_id": pid})
    return ok({"favorited": True, "fav_id": rec["id"]}, "已收藏")


@bp.delete("/<int:pid>")
def remove_favorite(pid: int):
    uid = current_user_id()
    fav = _find_fav(uid, pid)
    if not fav:
        return ok({"favorited": False}, "未收藏")
    favorite_repo.delete(fav["id"])
    return ok({"favorited": False}, "已取消收藏")


@bp.post("/<int:pid>/toggle")
def toggle_favorite(pid: int):
    if not product_repo.get(pid):
        return fail(404, "商品不存在")
    uid = current_user_id()
    fav = _find_fav(uid, pid)
    if fav:
        favorite_repo.delete(fav["id"])
        return ok({"favorited": False}, "已取消收藏")
    rec = favorite_repo.create({"user_id": uid, "product_id": pid})
    return ok({"favorited": True, "fav_id": rec["id"]}, "已收藏")


@bp.get("/<int:pid>")
def check_favorite(pid: int):
    """前端进入详情页快速回填爱心状态。"""
    fav = _find_fav(current_user_id(), pid)
    return ok({"favorited": bool(fav), "fav_id": fav["id"] if fav else None})
