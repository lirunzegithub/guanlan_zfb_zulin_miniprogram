"""原生 threading 定时任务（不依赖 apscheduler）。

当前任务：
  tick_track_sf_delivery     【主链路】定期查顺丰真实签收轨迹，签收即 recv → using，
                             并把归还日按真实签收重算（仅提前签收时）
  tick_advance_lease         【硬保底】每小时扫描 recv 状态订单，物流期已过的自动
                             recv → using，同步支付宝订单中心（IN_DELIVERY → IN_THE_LEASE）
  tick_cancel_stale_audit    定期扫 audit 状态订单，超 24h 仍未完成免押/付押金的
                             清理掉（可在后台设置关闭；取消前先向支付宝对账，
                             已冻结成功的推进为待发货而不是取消）
  tick_retry_cancel_refund  押金已解冻、租金退款未完成时重试固定退款请求；
                            成功即 pending_cancel → cancelled，绝不重复解冻押金

为什么不用 apscheduler：
  Werkzeug debug=True 的重载机制会让 BackgroundScheduler 出现行为微妙的 race
  （父子进程都启动一份 scheduler，且部分场景 tick 不触发），改用 Python 标准库
  threading 跑后台循环最简单可控。生产固定单 worker；若未来切多 worker，
  必须先把资金/库存终态升级为 SQLite 事务 + 状态 CAS。

设计：
- 用 status 字段做顺序重放幂等；单 worker 的多线程终态竞争由 routes 内 RLock 保护
- 失败不抛错，整轮扫描中单条订单异常不影响其他订单
- 物流期取值优先级：order.ship_days > settings.ship_free_days > 3
- recv → using 只有 advance_recv_to_using 一个出口，顺丰链路与保底链路都走它，
  谁先到谁生效，另一条自然扑空——不存在"两条链路各推一次"的可能
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

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

# 取消后的租金退款由系统退避重试；首期收租失败则不自动重扣，改由
# 客服联系客户后在后台手动发起。
_CANCEL_REFUND_MIN_GAP = 900
_CANCEL_REFUND_MAX_ATTEMPTS = 24


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


# ============ recv → using 的统一推进（两条链路共用） ============

def _date_add(ymd: str, n: int) -> str:
    """'YYYY-MM-DD' + n 天。解析不了返回空串。"""
    try:
        d = datetime.strptime((ymd or "").strip(), "%Y-%m-%d") + timedelta(days=n)
        return d.strftime("%Y-%m-%d")
    except (ValueError, TypeError, OverflowError):
        return ""


def _real_ship_days(order: dict, signed_at: int) -> int | None:
    """真实签收 → 真实物流天数。start_date 缺失或签收时间非法时返回 None。

    口径必须与全站既有语义一致（见 qianduan/utils/pricing.js buildTimeline）：
        签收日 = start_date + ship_days - 1     ← 物流期的最后一天
        起租日 = start_date + ship_days         ← 签收次日才开始计费
    反解得 ship_real = (签收日 - start_date) + 1。

    为什么不用"签收日直接当起租日"：那会凭空吃掉用户合同里的一天免租。
    保持"签收次日起租"，用机天数才恰好还是下单时买的 days 天。
    """
    start = (order.get("start_date") or "").strip()
    if not start or signed_at <= 0:
        return None
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return None
    signed_day = datetime.fromtimestamp(signed_at).date()
    # 签收早于 start_date（商家提前发货等）时钳到 0：物流期为 0 即当天起租
    return max(0, (signed_day - d0).days + 1)


def _reanchor_patch(order: dict, signed_at: int) -> dict:
    """提前签收 → 把物流期锚点改写成真实值，并据此重算归还日。

    【为什么改 ship_days 而不是直接改 end_date】
    小程序订单详情的实时租金累计（order-detail.js _buildRent）和确认页时间轴
    （utils/pricing.js buildTimeline）都是用 `start_date + ship_days` 反推起租日的。
    只改 end_date 会让"起租日"和"归还日"来自两套算法，页面上立刻对不上账。
    改锚点则两处推导自动跟着正确，前端一行都不用动。

    【只提前，不推后】真实物流天数 >= 原定物流期时原样不动。晚到的情况保底
    已经把订单推成"租赁中"了，此时再把归还日往后顺，等于用户拖慢物流就能白拿租期。

    金额一律不动：用户买的是 days 天用机，签收早晚不改变这个数，
    已冻结的 freeze_amount 更不能动。
    """
    days = int(order.get("days") or 0)
    start = (order.get("start_date") or "").strip()
    planned = int(order.get("ship_days") or 0)
    # 老入口下单不带日历日期，没有可重算的锚点
    if not start or not (order.get("end_date") or "").strip() or days <= 0 or planned <= 0:
        return {}

    real = _real_ship_days(order, signed_at)
    if real is None or real >= planned:
        return {}

    new_end = _date_add(start, real + days)
    if not new_end:
        return {}
    return {
        "ship_days": real,
        "end_date":  new_end,
        # 原值只在第一次重算时落，重复推进不会把它覆盖成已改写过的值
        "ship_days_planned": int(order.get("ship_days_planned") or 0) or planned,
    }


def advance_recv_to_using(
    oid: str,
    *,
    started_at: int,
    delivered_at: int = 0,
    source: str = "",
    reason: str,
) -> bool:
    """把订单从 recv 推进到 using。两条链路（顺丰签收 / 定时器保底）唯一的出口。

    幂等：重新读一次订单，status 已不是 recv 就什么都不做（别的 worker 或
    人工操作抢先推进过）。返回 True 表示本次由本调用推进成功。

    Args:
        started_at:   写入 lease_started_at 的时间戳
        delivered_at: 真实签收时间（顺丰链路才有；保底链路传 0）
        source:       签收信息来源，"sf" / ""，落库备查
        reason:       同步支付宝时写进 notify_log 的原因
    """
    from app.storage.repos import order_repo
    from app.storage.order_ops import update_order

    cur = order_repo.get(oid)
    if not cur or cur.get("status") != "recv":
        return False

    patch = {"status": "using", "lease_started_at": started_at}
    if delivered_at:
        patch["delivered_at"] = delivered_at
        patch["delivered_source"] = source or ""
        # 提前签收才有得重算；重算与状态推进在同一次 update 里落，
        # 避免"状态已变、日期还没改"的中间态被前端读到
        patch.update(_reanchor_patch(cur, delivered_at))

    update_order(oid, patch, sync_reason=reason)
    return True


def _reconcile_stale_audit(order: dict) -> str:
    """取消前向支付宝核实 audit 订单的冻结状态（用户可能已付款但通知丢失/未达）。

    返回：
      "frozen"  已冻结成功，已推进 audit→send（补落 auth_no），不能取消
      "none"    支付宝确认无冻结，可安全取消
      "unknown" 查询失败，本轮跳过，下轮重试
    """
    from app.routes.alipay import (
        is_frozen, mark_freeze_success, query_active_freeze,
    )
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
    mark_freeze_success(oid, order)
    if res.get("auth_no") and not (order.get("alipay_auth_no") or "").strip():
        order_repo.update(oid, {"alipay_auth_no": res["auth_no"]})
    # 如果首期租金已经尝试过且失败，只保留异常状态交给客服沟通和后台
    # 手动重试；这里不能因为死单对账再次真实扣款。
    after = transition_freeze_done(oid)
    if (after or {}).get("status") == "send":
        logger.warning("tick_cancel_stale_audit: %s 对账发现已冻结成功，推进为待发货（不取消）", oid)
    else:
        # 冻结成功但租金没收上来：保持明确异常状态，交给客服联系客户后
        # 在后台手动点击“重试租金结算”，不进行循环自动扣款。
        logger.warning(
            "tick_cancel_stale_audit: %s 已冻结但租金未结清，保持 audit 等待人工处理（不取消）", oid,
        )
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
                continue  # 已被别的 worker / 支付回调 / freeze notify 推进了
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


def rent_capture_pending(order: dict) -> bool:
    """这单是否属于「押金已冻结成功、但首期租金还没结清」。

    后台列表与手动重试接口共用同一判据，避免两处口径漂移。
    冻结与否只认 freeze_confirmed：早先这里用的是"alipay_auth_no 非空"，
    而授权单 INIT（用户还没授权）阶段就有授权号，于是从未冻结成功的订单也被
    标成"授权成功·租金结算中"，还给出了会把它推进待发货的重试入口。
    """
    from app.routes.alipay import freeze_confirmed
    return (
        (order.get("status") or "") == "audit"
        and freeze_confirmed(order)
        and not order.get("rent_paid_at")
    )


def cancel_requires_rent_refund(order: dict) -> bool:
    """该取消单是否按业务规则需要退首期租金。

    新订单由进入 pending_cancel 的入口显式写入；老订单仅兼容有用户申请
    时间、且不是后台强制取消的记录，避免把历史履约中强制关单误判为全额退款。
    """
    marker = order.get("cancel_refund_rent")
    if marker is not None:
        return bool(marker)
    return bool(order.get("cancel_requested_at")) and order.get("cancelled_by") != "admin_force"


def cancel_refund_pending(order: dict) -> bool:
    """是否属于“押金释放已完成，但首期租金还没退成功”。"""
    return (
        (order.get("status") or "") == "pending_cancel"
        and cancel_requires_rent_refund(order)
        and bool(order.get("unfreeze_completed_at"))
        and bool(order.get("rent_paid_at"))
        and not order.get("rent_refunded_at")
    )


def tick_retry_cancel_refund() -> dict:
    """自动重试“解冻已成功、退租金失败”的取消单。

    transition_unfreeze_done 会复用固定 rent_refund_request_no，因此这里只会
    重试同一笔退款，不会重复退钱；unfreeze_completed_at 又确保本链路
    绝不重新调用押金解冻。
    """
    from app.storage.repos import order_repo
    from app.routes.orders import transition_unfreeze_done

    now = int(time.time())
    summary = {"scanned": 0, "retried": 0, "cancelled": 0, "skipped": 0, "errors": 0}
    try:
        candidates = order_repo.list(status="pending_cancel")
    except Exception as e:
        logger.warning("tick_retry_cancel_refund list failed: %s", e)
        return summary

    for o in candidates:
        oid = o.get("id") or ""
        if not oid or not cancel_refund_pending(o):
            continue
        summary["scanned"] += 1
        if int(o.get("rent_refund_attempts") or 0) >= _CANCEL_REFUND_MAX_ATTEMPTS:
            summary["skipped"] += 1
            continue
        if now - int(o.get("rent_refund_last_at") or 0) < _CANCEL_REFUND_MIN_GAP:
            summary["skipped"] += 1
            continue
        try:
            summary["retried"] += 1
            after = transition_unfreeze_done(oid)
            if (after or {}).get("status") == "cancelled":
                summary["cancelled"] += 1
                logger.warning("tick_retry_cancel_refund: %s 租金已退，订单已取消", oid)
        except Exception as e:
            summary["errors"] += 1
            logger.warning("tick_retry_cancel_refund oid=%s err: %s", oid, e)

    if summary["retried"] or summary["errors"]:
        logger.warning("tick_retry_cancel_refund summary: %s", summary)
    return summary


def tick_advance_lease() -> dict:
    """【硬保底】扫描 status=recv 且物流期已过的订单，推进到 using。
    返回 {scanned, advanced, errors} 便于排查。

    这是对接顺丰之前就有的唯一链路，现在降级为保底：顺丰没配、不是顺丰单、
    轨迹查不到、接口挂了……最终都由它到点推进。它只会让跳变发生得不晚于
    「发货时间 + 物流免租期」，不依赖任何外部系统。
    """
    from app.storage.repos import order_repo

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

        # 幂等推进（顺丰链路可能已经抢先推过，advance_recv_to_using 内部会挡住）
        try:
            if advance_recv_to_using(
                oid, started_at=now, reason="auto_lease_started",
            ):
                summary["advanced"] += 1
                logger.info("tick_advance_lease: %s recv → using (shipped_at=%s)", oid, shipped_at)
        except Exception as e:
            summary["errors"] += 1
            logger.warning("tick_advance_lease oid=%s err: %s", oid, e)

    if summary["scanned"]:
        logger.info("tick_advance_lease summary: %s", summary)
    return summary


def tick_track_sf_delivery() -> dict:
    """【主链路】用顺丰真实签收轨迹把 recv 订单推进到 using。

    只处理 status=recv 且 logistics_company=SF 且有运单号的订单。
    未配置顺丰凭据时整轮跳过——不是错误，是"没对接"的正常状态，
    这些订单照常由 tick_advance_lease 到点保底推进。

    单条订单的查询失败不影响其它订单，也不改任何状态：保持 recv 等下一轮，
    真到了物流期还没查出来，保底会兜住。

    返回 {scanned, signed, in_transit, errors} 便于排查。
    """
    from app import sf_client
    from app.storage.repos import order_repo

    summary = {"scanned": 0, "signed": 0, "in_transit": 0, "errors": 0}
    if not sf_client.is_configured():
        return summary          # 未对接顺丰，全量走保底

    try:
        candidates = order_repo.list(status="recv")
    except Exception as e:
        logger.warning("tick_track_sf_delivery list failed: %s", e)
        return summary

    for o in candidates:
        oid = o.get("id") or ""
        if not oid or (o.get("logistics_company") or "").upper() != "SF":
            continue
        waybill = (o.get("logistics_no") or "").strip()
        if not waybill:
            continue
        summary["scanned"] += 1

        try:
            phone = ((o.get("address_snapshot") or {}).get("receiver_phone") or "")
            status, payload = sf_client.query_signed_at(waybill, phone)
            if status == sf_client.STATUS_IN_TRANSIT:
                summary["in_transit"] += 1
                continue
            if status != sf_client.STATUS_SIGNED:
                # not_configured 在上面已挡掉，走到这里就是网络/鉴权/解析失败
                summary["errors"] += 1
                logger.warning("tick_track_sf_delivery oid=%s 运单=%s 查询失败：%s",
                               oid, waybill, payload)
                continue

            signed_at = int(payload)
            # 前值先抓成不可变快照：repo 是否返回副本不该由日志来赌
            before = (o.get("ship_days"), o.get("end_date"))
            if advance_recv_to_using(
                oid,
                started_at=signed_at,
                delivered_at=signed_at,
                source="sf",
                reason="sf_signed",
            ):
                summary["signed"] += 1
                fresh = order_repo.get(oid) or {}
                logger.warning(
                    "tick_track_sf_delivery: %s recv → using（顺丰签收 %s，运单 %s）"
                    "物流期 %s→%s 归还日 %s→%s",
                    oid, time.strftime("%Y-%m-%d %H:%M", time.localtime(signed_at)), waybill,
                    before[0], fresh.get("ship_days"),
                    before[1], fresh.get("end_date"),
                )
        except Exception as e:
            summary["errors"] += 1
            logger.warning("tick_track_sf_delivery oid=%s err: %s", oid, e)

    if summary["scanned"]:
        logger.info("tick_track_sf_delivery summary: %s", summary)
    return summary


# ============ 原生 threading 循环 ============

# audit 死单清理扫描间隔（秒）；超时阈值是 24h，10 分钟颗粒度足够
_AUDIT_TICK_INTERVAL = 600
# 物流期推进扫描间隔（秒）；1 小时颗粒度即可
_ADVANCE_LEASE_INTERVAL = 3600
# 顺丰轨迹查询间隔（秒）。比保底扫描密，签收后半小时内就能跳变；
# 又不至于把丰桥的查询配额打满（每轮只查 status=recv 的顺丰单，通常个位数）。
_SF_TRACK_INTERVAL = 1800


def _run_loop() -> None:
    """后台单线程主循环。

    每 _AUDIT_TICK_INTERVAL 秒跑一次 tick_cancel_stale_audit；
    每 _SF_TRACK_INTERVAL 秒跑一次 tick_track_sf_delivery（顺丰签收，主链路）；
    每 _ADVANCE_LEASE_INTERVAL 秒跑一次 tick_advance_lease（物流期到点，硬保底）。
    后两者都叠加在 audit tick 上触发。

    顺序上先跑顺丰再跑保底：同一轮里若顺丰刚查出签收，保底扫到时订单已经不是
    recv，自然跳过，不会覆盖掉真实签收时间。反过来则会丢掉签收时间的精度。

    用 Event.wait 替代 time.sleep，便于进程退出时被 _stop_event 立即唤醒。
    单个 tick 抛异常会被 catch，写 warning 但不中断循环。
    """
    logger.warning("scheduler loop entering (audit tick=%ds, sf tick=%ds, advance tick=%ds)",
                   _AUDIT_TICK_INTERVAL, _SF_TRACK_INTERVAL, _ADVANCE_LEASE_INTERVAL)
    last_advance = 0
    last_sf = 0
    while not _stop_event.is_set():
        try:
            tick_cancel_stale_audit()
        except Exception as e:
            logger.warning("tick_cancel_stale_audit crashed: %s", e)
        try:
            tick_retry_cancel_refund()
        except Exception as e:
            logger.warning("tick_retry_cancel_refund crashed: %s", e)
        now = int(time.time())
        if now - last_sf >= _SF_TRACK_INTERVAL:
            try:
                tick_track_sf_delivery()
            except Exception as e:
                logger.warning("tick_track_sf_delivery crashed: %s", e)
            last_sf = now
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

    生产约束为 gunicorn workers=1 + gthread。多 worker 会各起一个调度线程，
    而进程内 RLock 无法跨进程保护资金/库存终态，切换前需先实现 DB 状态 CAS。
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
