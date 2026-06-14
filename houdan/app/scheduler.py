"""原生 threading 定时任务（不依赖 apscheduler）。

当前两个任务：
  tick_advance_lease         每小时扫描 recv 状态订单，物流期已过的自动 recv → using
                             并同步到支付宝订单中心（IN_DELIVERY → IN_THE_LEASE）
  tick_cancel_stale_audit    每分钟扫 audit 状态订单，超 60s 未完成免押的自动取消

为什么不用 apscheduler：
  Werkzeug debug=True 的重载机制会让 BackgroundScheduler 出现行为微妙的 race
  （父子进程都启动一份 scheduler，且部分场景 tick 不触发），改用 Python 标准库
  threading 跑后台循环最简单可控；订单状态推进本身就是幂等的，多进程重启叠加
  执行也无副作用。

设计：
- 用 status 字段做幂等：每个 transition 都只在原状态成立时推进，多 worker 重复扫描安全
- 失败不抛错，整轮扫描中单条订单异常不影响其他订单
- 物流期取值优先级：order.ship_days > settings.ship_free_days > 3
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop_event = threading.Event()
# 兼容老代码引用（已废弃）；外部读到非 None 即认为"调度已启"
_scheduler = None

# audit 状态超过此秒数仍未完成免押 → 自动取消
# 设计依据：正常下单是"创建→免押弹窗→成功"一气呵成（几十秒级别）。
# 用户中途退出/失败，再回来重发 freeze 会因 out_order_no 冲突报错——
# 与其修复重试，不如让 audit 短时超时即取消，引导用户重新下单。
# 注：scheduler 每分钟扫一次，所以实际取消时间在 60–120 秒之间（最差差一个 tick）。
AUDIT_TIMEOUT_SECONDS = 1 * 60


def _ship_days_for(order: dict) -> int:
    """物流免租期（天）。订单本身 ship_days > 系统设置 ship_free_days > 兜底 3。"""
    v = int(order.get("ship_days") or 0)
    if v > 0:
        return v
    try:
        from app.settings import get as _setting_get
        v = int(_setting_get("ship_free_days") or 0)
        if v > 0:
            return v
    except Exception:
        pass
    return 3


def tick_cancel_stale_audit() -> dict:
    """扫 status=audit 且创建时间超过 AUDIT_TIMEOUT_SECONDS 的订单，自动取消。

    audit→cancelled 走 update_order 拦截器，会自动 sync 支付宝订单中心
    （DEPOSIT_WAIVER → CLOSED）。优惠券同步退回。
    """
    from app.storage.repos import order_repo
    from app.storage.order_ops import update_order
    from app.routes.orders import _refund_coupon_if_any

    now = int(time.time())
    summary = {"scanned": 0, "cancelled": 0, "errors": 0}

    try:
        candidates = order_repo.list(status="audit")
    except Exception as e:
        logger.warning("tick_cancel_stale_audit list failed: %s", e)
        return summary

    # 临时诊断：每次 tick 必打一条 heartbeat（看 tick 是否真的被调度 + audit 订单的具体状态）
    # 排查完后可降回 info / 去掉
    if candidates:
        ages = sorted(
            (now - int(o.get("created_at") or 0)) for o in candidates
            if o.get("created_at")
        )
        logger.warning(
            "tick_cancel_stale_audit heartbeat: %d audit orders, ages(s)=%s, threshold=%ds",
            len(candidates), ages, AUDIT_TIMEOUT_SECONDS,
        )
    else:
        logger.warning("tick_cancel_stale_audit heartbeat: 0 audit orders")

    for o in candidates:
        summary["scanned"] += 1
        oid = o.get("id") or ""
        created_at = int(o.get("created_at") or 0)
        if not oid or not created_at:
            logger.warning("  skip %s: missing oid or created_at (created_at=%s)", oid, o.get("created_at"))
            continue
        if now - created_at < AUDIT_TIMEOUT_SECONDS:
            logger.warning("  skip %s: created %ds ago, not yet timeout", oid, now - created_at)
            continue  # 还在容忍期内

        try:
            cur = order_repo.get(oid)
            if not cur or cur.get("status") != "audit":
                continue  # 已被别的 worker / freeze notify 推进了
            update_order(oid, {
                "status":       "cancelled",
                "cancelled_at": now,
                "cancelled_by": "auto_audit_timeout",
            }, sync_reason="auto_audit_timeout")
            _refund_coupon_if_any(cur)
            summary["cancelled"] += 1
            logger.warning(
                "tick_cancel_stale_audit: %s audit → cancelled (created %ds ago)",
                oid, now - created_at,
            )
        except Exception as e:
            summary["errors"] += 1
            logger.warning("tick_cancel_stale_audit oid=%s err: %s", oid, e)

    if summary["cancelled"] or summary["errors"]:
        logger.warning("tick_cancel_stale_audit summary: %s", summary)
    return summary


def tick_advance_lease() -> dict:
    """扫描 status=recv 且物流期已过的订单，推进到 using。
    返回 {scanned, advanced, errors} 便于排查。
    """
    from app.storage.repos import order_repo
    from app.storage.order_ops import update_order  # status 变化由拦截器自动 sync

    now = int(time.time())
    summary = {"scanned": 0, "advanced": 0, "errors": 0}

    try:
        candidates = order_repo.list(status="recv")
    except Exception as e:
        logger.warning("tick_advance_lease list failed: %s", e)
        return summary

    for o in candidates:
        summary["scanned"] += 1
        oid = o.get("id") or ""
        shipped_at = int(o.get("shipped_at") or 0)
        if not oid or not shipped_at:
            continue
        deadline = shipped_at + _ship_days_for(o) * 86400
        if now < deadline:
            continue  # 物流期还没过

        # 幂等推进
        try:
            cur = order_repo.get(oid)
            if not cur or cur.get("status") != "recv":
                continue  # 已被别的 worker 推进了
            update_order(oid, {"status": "using", "lease_started_at": now},
                         sync_reason="auto_lease_started")
            summary["advanced"] += 1
            logger.info("tick_advance_lease: %s recv → using (shipped_at=%s)", oid, shipped_at)
        except Exception as e:
            summary["errors"] += 1
            logger.warning("tick_advance_lease oid=%s err: %s", oid, e)

    if summary["scanned"]:
        logger.info("tick_advance_lease summary: %s", summary)
    return summary


# ============ 原生 threading 循环 ============

# audit 超时扫描间隔（秒）；改这里可调，但不需要小于 5s（无意义浪费 CPU）
_AUDIT_TICK_INTERVAL = 30
# 物流期推进扫描间隔（秒）；1 小时颗粒度即可
_ADVANCE_LEASE_INTERVAL = 3600


def _run_loop() -> None:
    """后台单线程主循环。

    每 _AUDIT_TICK_INTERVAL 秒跑一次 tick_cancel_stale_audit；
    每 _ADVANCE_LEASE_INTERVAL 秒跑一次 tick_advance_lease（在 audit tick 上叠加触发）。

    用 Event.wait 替代 time.sleep，便于进程退出时被 _stop_event 立即唤醒。
    单个 tick 抛异常会被 catch，写 warning 但不中断循环。
    """
    logger.warning("scheduler loop entering (audit tick=%ds, advance tick=%ds)",
                   _AUDIT_TICK_INTERVAL, _ADVANCE_LEASE_INTERVAL)
    last_advance = 0
    while not _stop_event.is_set():
        try:
            tick_cancel_stale_audit()
        except Exception as e:
            logger.warning("tick_cancel_stale_audit crashed: %s", e)
        now = int(time.time())
        if now - last_advance >= _ADVANCE_LEASE_INTERVAL:
            try:
                tick_advance_lease()
            except Exception as e:
                logger.warning("tick_advance_lease crashed: %s", e)
            last_advance = now
        # 用 wait 而不是 sleep，停止时可立即响应
        _stop_event.wait(_AUDIT_TICK_INTERVAL)


def start_scheduler() -> None:
    """在 Flask 应用启动时调用。重复调用安全（线程只启一次）。

    多进程场景（gunicorn 多 worker / Werkzeug debug 重载）：每个进程都会启动
    一个独立后台线程，但 tick 内部都是幂等的，重复执行只是多扫几次表，无副作用。
    """
    global _thread, _scheduler
    if _thread is not None and _thread.is_alive():
        return

    _stop_event.clear()
    _thread = threading.Thread(target=_run_loop, name="scheduler-loop", daemon=True)
    _thread.start()
    _scheduler = _thread   # 兼容外部"scheduler 非 None 即起" 的判断
    logger.warning(
        "scheduler started (native threading): audit timeout=%ds, audit tick=%ds, advance tick=%ds",
        AUDIT_TIMEOUT_SECONDS, _AUDIT_TICK_INTERVAL, _ADVANCE_LEASE_INTERVAL,
    )


def stop_scheduler() -> None:
    """优雅停止后台线程；进程退出时不调也行（daemon 自动结束）。"""
    global _thread, _scheduler
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=2)
    _thread = None
    _scheduler = None
