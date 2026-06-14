"""优惠券公共工具：满减券的有效性判断 / 抵扣计算。

仅一种格式：满 threshold 元减 discount 元。
- threshold >= discount > 0（保证不会出现负数订单）
- 订单实付金额 = max(0, original_amount - discount)（理论上不会 <0，因为有 threshold 约束）
"""
from __future__ import annotations

import time
from typing import Optional

from app.storage.repos import coupon_repo, user_coupon_repo


def coupon_is_active(c: dict, now: Optional[int] = None) -> bool:
    """模板维度：状态 on + 在有效期内 + 未抢光。"""
    if not c or c.get("status") != "on":
        return False
    now = int(now or time.time())
    start = int(c.get("start_at") or 0)
    end = int(c.get("end_at") or 0)
    if start and now < start:
        return False
    if end and now > end:
        return False
    total = int(c.get("total_quantity") or 0)
    claimed = int(c.get("claimed_quantity") or 0)
    if total > 0 and claimed >= total:
        return False
    return True


def user_coupon_is_usable(uc: dict, now: Optional[int] = None) -> bool:
    """领取后的实例：未使用 + 未过期。"""
    if not uc or uc.get("status") != "unused":
        return False
    now = int(now or time.time())
    end = int(uc.get("end_at") or 0)
    if end and now > end:
        return False
    return True


def applicable_to_amount(uc_or_c: dict, amount: float) -> bool:
    """金额是否达到满减门槛。"""
    try:
        threshold = float(uc_or_c.get("threshold") or 0)
    except (TypeError, ValueError):
        return False
    return float(amount or 0) >= threshold


def sync_expired_user_coupons(user_id: str) -> None:
    """惰性刷新：把当前用户已过期的 unused 实例置为 expired。
    每次列表 / 选择优惠券时调用一次，避免后台跑批。
    """
    now = int(time.time())
    for uc in user_coupon_repo.list(user_id=user_id, status="unused"):
        end = int(uc.get("end_at") or 0)
        if end and now > end:
            user_coupon_repo.update(uc["id"], {"status": "expired"})


def calc_discount(uc: dict, amount: float) -> float:
    """返回最终的抵扣金额（不会让订单为负）。门槛未达返回 0。"""
    if not applicable_to_amount(uc, amount):
        return 0.0
    discount = float(uc.get("discount") or 0)
    if discount <= 0:
        return 0.0
    # 理论上 threshold >= discount 已保证 amount - discount >= 0
    return round(min(discount, float(amount or 0)), 2)
