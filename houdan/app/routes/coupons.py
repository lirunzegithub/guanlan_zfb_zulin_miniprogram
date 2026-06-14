"""用户端优惠券接口。

接口契约（全部前缀 /api）:
  GET  /api/coupons                          → 列表：所有 status=on 且有效的券（详情页/中心）
                                               可选 ?amount=X 计算每张的适用状态（usable_for_amount）
  POST /api/coupons/<id>/claim               → 当前用户领取一张
  GET  /api/user/coupons?status=unused|used|expired
                                             → 我的优惠券（默认全部）
  GET  /api/user/coupons/match?amount=X      → 我的可用券（unused + 未过期 + 满足门槛），按抵扣降序
"""
from __future__ import annotations

import time
from flask import Blueprint, request

from flask import g, has_request_context

from app.response import ok, fail
from app.storage.repos import coupon_repo, user_coupon_repo
from app.current_user import current_user_id
from app.coupons import (
    coupon_is_active, user_coupon_is_usable, applicable_to_amount,
    sync_expired_user_coupons, calc_discount,
)


def _optional_user_id() -> str | None:
    """允许匿名调用：拿不到登录态时返回 None，业务字段降级即可。"""
    if not has_request_context():
        return None
    return getattr(g, "user_id", None)

bp_public = Blueprint("coupons", __name__)
bp_user = Blueprint("user_coupons", __name__)


def _coupon_card(c: dict, uid: str | None, amount: float | None) -> dict:
    """详情页/优惠券中心展示用：补 user_claimed + usable_for_amount。uid 为空走匿名降级。"""
    out = dict(c)
    if uid:
        held = user_coupon_repo.list(user_id=uid, coupon_id=c["id"])
    else:
        held = []
    out["user_held"] = len(held)
    out["user_unused"] = sum(1 for h in held if h.get("status") == "unused")
    # 领取上限：per_user_limit=0 不限
    limit = int(c.get("per_user_limit") or 0)
    out["claimable"] = (limit == 0) or (len(held) < limit)
    # 库存
    total = int(c.get("total_quantity") or 0)
    claimed = int(c.get("claimed_quantity") or 0)
    out["sold_out"] = total > 0 and claimed >= total
    if amount is not None:
        out["usable_for_amount"] = applicable_to_amount(c, amount)
    return out


@bp_public.get("")
def list_active_coupons():
    """所有上架且在有效期内的券；?amount=X 用于详情页判断"对当前订单可用"。
    允许匿名调用：未登录时 user_held / user_unused 都为 0，claimable 仅按 per_user_limit 推断。
    """
    amount = request.args.get("amount", type=float)
    uid = _optional_user_id()
    items = [c for c in coupon_repo.list() if coupon_is_active(c)]
    # 门槛升序，便于用户从最易达到的看起
    items.sort(key=lambda x: float(x.get("threshold") or 0))
    return ok({
        "list": [_coupon_card(c, uid, amount) for c in items],
        "total": len(items),
    })


@bp_public.post("/<int:cid>/claim")
def claim_coupon(cid):
    c = coupon_repo.get(cid)
    if not c:
        return fail(404, "优惠券不存在")
    if not coupon_is_active(c):
        return fail(1, "该券已下架或已抢光")

    uid = current_user_id()
    held = user_coupon_repo.list(user_id=uid, coupon_id=cid)
    limit = int(c.get("per_user_limit") or 0)
    if limit > 0 and len(held) >= limit:
        return fail(1, f"每人最多领取 {limit} 张")

    now = int(time.time())
    uc = user_coupon_repo.create({
        "user_id": uid,
        "coupon_id": cid,
        "name": c.get("name", ""),
        "threshold": float(c.get("threshold") or 0),
        "discount": float(c.get("discount") or 0),
        "status": "unused",
        "start_at": int(c.get("start_at") or 0),
        "end_at": int(c.get("end_at") or 0),
        "order_id": "",
        "claimed_at": now,
        "used_at": 0,
    })
    # 模板上"已领数量"+1（统计 + 控量）
    coupon_repo.update(cid, {"claimed_quantity": int(c.get("claimed_quantity") or 0) + 1})
    return ok(uc, "领取成功")


@bp_user.get("")
def my_coupons():
    """我的优惠券；?status=unused|used|expired，缺省返回全部并按状态分组。"""
    uid = current_user_id()
    sync_expired_user_coupons(uid)
    status = (request.args.get("status") or "").strip()
    items = user_coupon_repo.list(user_id=uid)
    items.sort(key=lambda x: -int(x.get("claimed_at") or 0))
    if status in ("unused", "used", "expired"):
        items = [x for x in items if x.get("status") == status]
    return ok({"list": items, "total": len(items)})


@bp_user.get("/match")
def match_coupons():
    """下单页：根据订单 amount 返回当前可用券（已按抵扣金额降序）。"""
    uid = current_user_id()
    sync_expired_user_coupons(uid)
    amount = request.args.get("amount", type=float) or 0.0
    items = user_coupon_repo.list(user_id=uid, status="unused")
    usable = [
        {**uc, "discount_amount": calc_discount(uc, amount)}
        for uc in items
        if user_coupon_is_usable(uc) and applicable_to_amount(uc, amount)
    ]
    usable.sort(key=lambda x: -float(x.get("discount_amount") or 0))
    return ok({
        "list": usable,
        "total": len(usable),
        "amount": round(float(amount), 2),
    })
