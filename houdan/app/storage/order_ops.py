"""订单更新的统一入口（含 status 变更拦截器）。

设计目标：把"订单 status 变化 → 同步支付宝订单中心"这条规则收口到一处，
让业务代码只关心状态机本身，不必每次 update 后都记得手动调 sync_order。

使用：
    from app.storage.order_ops import update_order
    update_order(oid, {"status": "send", "send_at": ...})
    update_order(oid, {"status": "cancelled", "cancelled_at": ...}, sync_reason="user_cancel")

行为：
    - patch 里写了 status 且实际变化（before != after）→ 触发 sync_order
    - patch 里没写 status，或写了但和当前值相同 → 不 sync
    - sync_order 失败不抛错，sync_err 字段会自动落库（同 order_sync 既有行为）

为什么不直接覆盖 order_repo.update：
    sync_order 自身会把 sync_at / sync_ok / sync_status / sync_err 写回订单，
    若所有 update 都触发同步会无限递归。改用显式入口函数 update_order，
    sync_order 内部的元数据回写继续用裸 order_repo.update 避开拦截器。
"""
from __future__ import annotations

import logging

from app.storage.repos import order_repo

logger = logging.getLogger(__name__)


def update_order(
    oid: str,
    patch: dict,
    *,
    sync_reason: str | None = None,
) -> dict | None:
    """订单更新统一入口。patch 里改了 status 时自动 sync 到支付宝订单中心。

    Args:
        oid:          订单 id。
        patch:        要写入的字段 dict（与 order_repo.update 同语义）。
        sync_reason:  可选；写到 notify_log 里方便排查。不传时用 "before->after" 兜底。

    Returns:
        更新后的订单 dict（同 order_repo.update）。
    """
    before = order_repo.get(oid)
    after  = order_repo.update(oid, patch)

    # 只在 status 真实变化时触发 sync
    if (
        before is not None
        and after is not None
        and "status" in (patch or {})
        and before.get("status") != after.get("status")
    ):
        # 延迟 import 避免循环依赖（order_sync → alipay_client → ... ）
        from app.order_sync import sync_order
        reason = sync_reason or f"{before.get('status') or 'none'}->{after.get('status') or 'none'}"
        try:
            sync_order(oid, reason=reason)
        except Exception as e:
            # sync_order 自身已经 catch + 落 sync_err；这里再兜一层防止罕见的二次异常炸到调用方
            logger.warning("update_order auto-sync failed oid=%s reason=%s err=%s", oid, reason, e)

    return after
