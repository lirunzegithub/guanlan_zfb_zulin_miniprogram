"""原生 threading 定时任务（不依赖 apscheduler）。

当前两个任务：
  tick_advance_lease         每小时扫描 recv 状态订单，物流期已过的自动 recv → using
                             并同步到支付宝订单中心（IN_DELIVERY → IN_THE_LEASE）
  tick_cancel_stale_audit    定期扫 audit 状态订单，超 24h 仍未完成免押/付押金的
                             清理掉（可在后台设置关闭；取消前先向支付宝对账，
                             已冻结成功的推进为待发货而不是取消）

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

# audit 状态超过此秒数仍未完成免押/付押金 → 自动取消（死单清理）。
# 历史：这里曾是 60 秒——当年 out_order_no 唯一性限制导致中途退出无法重试，
# 只能"短超时取消引导重新下单"。冻结续号（_A2/_A3…）落地后重试已经可用，
# audit 变成可停留、可从订单页继续支付的正常状态，超时取消随之降级为
# 长周期死单清理（商品可能下架/调价，不宜无限期保留未支付订单）。
# 开关：settings.auto_cancel_stale_audit（后台设置页可关，默认开）。
# 取消前先向支付宝对账，已冻结成功的推进为待发货，杜绝"已付款订单被取消"。
AUDIT_TIMEOUT_SECONDS = 24 * 3600


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


def _reconcile_stale_audit(order: dict) -> str:
    """取消前向支付宝核实 audit 订单的冻结状态（用户可能已付款但通知丢失/未达）。

    返回：
      "frozen"  已冻结成功，已推进 audit→send（补落 auth_no），不能取消
      "none"    支付宝确认无冻结，可安全取消
      "unknown" 查询失败，本轮跳过，下轮重试
    """
    from app.routes.alipay import query_active_freeze, is_frozen
    oid = order.get("id") or ""
    try:
        res = query_active_freeze(order)
    except Exception as e:
        logger.warning("tick_cancel_stale_audit reconcile %s query failed: %s", oid, e)
        return "unknown"
    if not is_frozen(res):
        return "none"
    from app.storage.repos import order_repo
    from app.routes.orders import transition_freeze_done
    if res.get("auth_no") and not (order.get("alipay_auth_no") or "").strip():
        order_repo.update(oid, {"alipay_auth_no": res["auth_no"]})
    transition_freeze_done(oid)
    logger.warning("tick_cancel_stale_audit: %s 对账发现已冻结成功，推进为待发货（不取消）", oid)
    return "frozen"


def tick_cancel_stale_audit() -> dict:
    """扫 status=audit 且创建时间超过 AUDIT_TIMEOUT_SECONDS 的订单，清理取消。

    - settings.auto_cancel_stale_audit 关闭时整轮跳过（订单无限期停留在待免押）。
    - 发起过冻结的订单先对账：已冻结 → 推进待发货；查询失败 → 本轮不动。
    - audit→cancelled 走 update_order 拦截器，会自动 sync 支付宝订单中心
      （DEPOSIT_WAIVER → CLOSED）。优惠券同步退回。
    """
    from app.storage.repos import order_repo
    from app.storage.order_ops import update_order
    from app.routes.orders import _refund_coupon_if_any

    now = int(time.time())
    summary = {"scanned": 0, "cancelled": 0, "advanced": 0, "errors": 0}

    try:
        from app.settings import get as setting_get
        if not setting_get("auto_cancel_stale_audit"):
            return summary  # 后台已关闭自动清理
    except Exception as e:
        logger.warning("tick_cancel_stale_audit read settings failed: %s", e)
        return summary

    try:
        candidates = order_repo.list(status="audit")
    except Exception as e:
        logger.warning("tick_cancel_stale_audit list failed: %s", e)
        return summary

    for o in candidates:
        summary["scanned"] += 1
        oid = o.get("id") or ""
        created_at = int(o.get("created_at") or 0)
        if not oid or not created_at:
            continue
        if now - created_at < AUDIT_TIMEOUT_SECONDS:
            continue  # 还在容忍期内

        try:
            cur = order_repo.get(oid)
            if not cur or cur.get("status") != "audit":
                continue  # 已被别的 worker / freeze notify 推进了
            # 取消前对账：只要发起过冻结就先问支付宝，防止取消已付款的订单
            if int(cur.get("alipay_freeze_attempts") or 0) > 0:
                verdict = _reconcile_stale_audit(cur)
                if verdict == "frozen":
                    summary["advanced"] += 1
                    continue
                if verdict == "unknown":
                    summary["errors"] += 1
                    continue
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

    if summary["cancelled"] or summary["advanced"] or summary["errors"]:
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

# audit 死单清理扫描间隔（秒）；超时阈值是 24h，10 分钟颗粒度足够
_AUDIT_TICK_INTERVAL = 600
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
