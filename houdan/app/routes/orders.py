"""订单接口（全 SQLite 持久化版）"""
import logging
import threading
from datetime import date, timedelta
import time
import uuid
from flask import Blueprint, request
from app.response import ok, fail
from app.storage.repos import (
    product_repo, sku_repo, address_repo, order_repo, user_coupon_repo, renewal_repo,
)
from app.storage.order_ops import update_order
from app.current_user import current_user_id, current_user
from app.pricing import (
    calc_amount, normalize_tiers, first_unit_price, substitute_zero_tiers, round_yuan,
)
from app.coupons import (
    user_coupon_is_usable, applicable_to_amount, calc_discount,
)
# 复用 products 路由里的相对→绝对 URL 转换：DB 里 covers/cover_url 存的是
# /product/asset/... 这种相对路径，小程序 <image> 无法当网络图加载，必须补全为
# https://<host>/... 否则会被当成本地 bundle 资源静默失败。
from app.routes.products import _abs as _abs_url

bp = Blueprint("orders", __name__)
logger = logging.getLogger(__name__)

# 业务硬约束：用机最少 3 天（不含物流期）。商品后台不允许配置覆盖。
MIN_RENT_DAYS = 3

# 前端订单 Tab：key 与 order.status 一一对应
# 注：原本 audit→awaiting_face→send 三档；芝麻免押本身已含活体校验，
# 二次人脸冗余且拉低转化，故 awaiting_face 已废弃，免押成功直接进 send。
# return_inspecting = 用户已寄回、商家核验中（核验通过 → unfreeze → done）
ORDER_STATUS_TABS = [
    {"key": "pay",               "name": "待付租金"},
    {"key": "audit",             "name": "待免押"},
    {"key": "send",              "name": "待发货"},
    {"key": "pending_cancel",    "name": "取消审核中"},
    {"key": "recv",              "name": "待收货"},
    {"key": "using",             "name": "租赁中"},
    {"key": "return",            "name": "待归还"},
    {"key": "overdue",           "name": "已逾期"},
    {"key": "return_inspecting", "name": "核验中"},
    {"key": "done",              "name": "已归还"},
    {"key": "cancelled",         "name": "已取消"},
]

# 用户可主动发起归还（填寄回快递信息）的状态白名单
_RETURN_SHIP_ALLOWED = frozenset({"using", "return", "overdue"})
_RENEWAL_ALLOWED = frozenset({"using", "return"})
_renewal_lock = threading.RLock()


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except (TypeError, ValueError):
        return None


def _renewal_view(r: dict) -> dict:
    out = dict(r)
    out["quoted_amount_text"] = f"{float(r.get('quoted_amount') or 0):.2f}"
    return out


def _renewal_quote(o: dict, new_end_date: str) -> tuple[dict | None, str]:
    if (o.get("status") or "") not in _RENEWAL_ALLOWED:
        return None, "当前订单状态不允许续租"
    old_end = _parse_date(o.get("end_date") or "")
    new_end = _parse_date(new_end_date)
    if not old_end or not new_end:
        return None, "请选择有效的新归还日期"
    renew_days = (new_end - old_end).days
    if renew_days < 1:
        return None, "新归还日期必须晚于当前归还日期"
    if renew_days > 60:
        return None, "单次续租最长 60 天"
    # 押金授权通常 360 天到期；为给归还、核验、扣款/解冻预留处理时间，
    # 新归还日必须不晚于授权到期日前 10 天。
    auth_start = int(o.get("send_at") or o.get("created_at") or 0)
    auth_deadline = date.fromtimestamp(auth_start) + timedelta(days=350) if auth_start else None
    if auth_deadline and new_end > auth_deadline:
        return None, f"新归还日需早于押金授权到期日 10 天（最晚 {auth_deadline.isoformat()}）"
    original_days = int(o.get("days") or 0)
    tiers = normalize_tiers(o.get("price_tiers") or [])
    if not tiers:
        return None, "订单缺少计费快照，请联系客服"
    new_total_days = original_days + renew_days
    amount = round_yuan(calc_amount(new_total_days, tiers) - calc_amount(original_days, tiers))
    if amount <= 0:
        # 租押分离（settings.allow_zero_rent）下的 0 元租金单：价格档本身就是 0，
        # 续租算不出增量金额，也没有可支付的续租单，只能转人工。与"配错价"区分开，
        # 免得用户拿到一句看不懂的"金额异常"。
        if float(o.get("amount") or 0) <= 0:
            return None, "租押分离状态续租请联系下单平台客服"
        return None, "续租金额异常，请联系客服"
    return {
        "order_id": o["id"], "original_end_date": old_end.isoformat(),
        "new_end_date": new_end.isoformat(), "renew_days": renew_days,
        "original_days": original_days, "new_total_days": new_total_days,
        "quoted_amount": amount, "quoted_amount_text": f"{amount:.2f}",
        "pricing_snapshot": tiers,
    }, ""


_USER_STATUS_LABEL = {
    "pay":               "待付租金",
    "audit":             "待免押",
    "send":              "待发货",
    "pending_cancel":    "取消审核中",
    "recv":              "待收货",
    "using":             "租赁中",
    "return":            "待归还",
    "overdue":           "已逾期",
    "return_inspecting": "核验中",
    "done":              "已归还",
    "cancelled":         "已取消",
}


def _enrich(o: dict) -> dict:
    """订单展示前的运行时增强：补 product_cover + status_label，前端订单详情/列表共用。"""
    out = dict(o)
    # 光影库存对接字段属于内部运营数据（仓库/成色/问题等），不下发给 C 端用户
    out.pop("item_huohao", None)
    out.pop("item_snapshot", None)
    pid = o.get("product_id")
    if pid:
        p = product_repo.get(pid) or {}
        covers = p.get("covers") if isinstance(p.get("covers"), list) else []
        raw_cover = (covers[0] if covers else "") or (p.get("cover_url") or "")
        # 必须补成绝对 URL，小程序 <image> 无法解析 / 开头的相对路径
        out["product_cover"] = _abs_url(raw_cover)
    else:
        out["product_cover"] = ""
    status = o.get("status") or ""
    out["status_label"] = _USER_STATUS_LABEL.get(status, status)
    if status == "audit" and o.get("alipay_auth_no") and not o.get("rent_paid_at"):
        out["status_label"] = "租金结算中"
    # pending_cancel 细分：商家已点同意并下发解冻请求 → "解冻中"
    if status == "pending_cancel" and o.get("unfreeze_dispatched_at"):
        out["status_label"] = "解冻中"
    # return_inspecting 细分：商家已点核验通过并下发解冻请求 → "解冻中"
    if status == "return_inspecting" and o.get("unfreeze_dispatched_at"):
        out["status_label"] = "解冻中"
    return out


def _default_address(uid: str) -> dict | None:
    addrs = [a for a in address_repo.list(user_id=uid) if a.get("is_default")]
    return addrs[0] if addrs else None


# ---------- 列表 / 状态 Tab ----------
@bp.get("/tabs")
def tabs():
    return ok(ORDER_STATUS_TABS)


@bp.get("")
def list_orders():
    status = request.args.get("status")
    uid = current_user_id()
    items = order_repo.list(user_id=uid)
    if status and status != "all":
        items = [o for o in items if o.get("status") == status]
    items.sort(key=lambda x: -int(x.get("created_at") or 0))
    return ok({"list": [_enrich(o) for o in items], "total": len(items)})


@bp.get("/<oid>")
def detail(oid):
    o = order_repo.get(oid)
    # 兼容芝麻"信用服务守约"链接回跳：URL 里的 id=${out_order_no} 由支付宝用
    # 授权订单号填充，可能带 _A2 等重试后缀；直查不到时按订单号还原再查一次。
    if not o:
        o = order_repo.get(order_id_from_out_order_no(oid))
    if not o:
        return fail(404, "订单不存在")
    return ok(_enrich(o))


# ---------- 续租 ----------
@bp.get("/<oid>/renewal/quote")
def renewal_quote(oid):
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != current_user_id():
        return fail(403, "无权操作")
    quote, err = _renewal_quote(o, request.args.get("new_end_date") or "")
    if not quote:
        return fail(1, err)
    return ok(quote)


@bp.get("/<oid>/renewals")
def renewal_list(oid):
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != current_user_id():
        return fail(403, "无权操作")
    items = renewal_repo.list(order_id=oid)
    items.sort(key=lambda x: -int(x.get("created_at") or 0))
    return ok({"list": [_renewal_view(x) for x in items]})


@bp.post("/<oid>/renewals")
def renewal_create(oid):
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    uid = current_user_id()
    if o.get("user_id") != uid:
        return fail(403, "无权操作")
    body = request.get_json(silent=True) or {}
    quote, err = _renewal_quote(o, body.get("new_end_date") or "")
    if not quote:
        return fail(1, err)

    # 同一订单只保留一个待支付单；同日期重复点击直接复用。
    with _renewal_lock:
        waiting = renewal_repo.find(order_id=oid, status="WAITING_PAY")
        if waiting:
            if waiting.get("new_end_date") == quote["new_end_date"]:
                return ok(_renewal_view(waiting))
            renewal_repo.update(waiting["id"], {
                "status": "CANCELLED", "cancelled_at": int(time.time()),
                "failure_reason": "用户重新选择续租日期",
            })

        rid = "R" + uuid.uuid4().hex[:15].upper()
        out_trade_no = rid + "P"
        rec = renewal_repo.create({
            "id": rid, "user_id": uid, "status": "WAITING_PAY",
            "out_trade_no": out_trade_no, **quote,
        })
    return ok(_renewal_view(rec), "续租单已创建")


@bp.post("/renewals/<rid>/pay")
def renewal_pay(rid):
    r = renewal_repo.get(rid)
    if not r:
        return fail(404, "续租单不存在")
    if r.get("user_id") != current_user_id():
        return fail(403, "无权操作")
    if r.get("status") == "COMPLETED":
        return ok({"completed": True, "renewal": _renewal_view(r)})
    if r.get("status") != "WAITING_PAY":
        return fail(1, "该续租单已不可支付")
    o = order_repo.get(r.get("order_id") or "")
    quote, err = _renewal_quote(o or {}, r.get("new_end_date") or "")
    if not quote or o.get("end_date") != r.get("original_end_date"):
        renewal_repo.update(rid, {
            "status": "CANCELLED", "cancelled_at": int(time.time()),
            "failure_reason": err or "订单租期已变更",
        })
        return fail(1, err or "订单租期已变更，请重新申请")
    try:
        from app.alipay_client import get_client
        pay = get_client().trade_create(
            r["out_trade_no"], float(r.get("quoted_amount") or 0),
            f"续租 - {o.get('product_name') or '租赁商品'}",
            buyer_id=current_user_id(),
            body=f"订单 {o['id']} 续租 {r.get('renew_days')} 天",
        )
        return ok({**pay, "renewal": _renewal_view(r)})
    except Exception as e:
        return fail(1, f"创建续租支付失败：{e}")


def complete_renewal(out_trade_no: str, *, trade_no: str = "", raw: dict | None = None) -> dict | None:
    """支付成功的唯一业务出口。通知和主动 query 都走这里，保证幂等。"""
    with _renewal_lock:
        r = renewal_repo.find(out_trade_no=out_trade_no)
        if not r:
            return None
        if r.get("status") == "COMPLETED":
            return r
        o = order_repo.get(r.get("order_id") or "")
        now = int(time.time())
        raw = raw or {}
        try:
            paid_amount = float(raw.get("total_amount") or raw.get("receipt_amount") or r.get("quoted_amount") or 0)
        except (TypeError, ValueError):
            paid_amount = -1
        buyer_id = (raw.get("buyer_id") or raw.get("buyer_user_id") or "").strip()
        invalid_payment = abs(paid_amount - float(r.get("quoted_amount") or 0)) > 0.001
        invalid_buyer = bool(buyer_id and buyer_id != (r.get("user_id") or ""))
        if (not o or o.get("status") not in _RENEWAL_ALLOWED
                or o.get("end_date") != r.get("original_end_date")
                or invalid_payment or invalid_buyer):
            reason = "支付成功，但订单已逾期或租期已变更，需人工处理"
            if invalid_payment: reason = "支付金额与续租报价不一致，需人工处理"
            if invalid_buyer: reason = "付款用户与续租申请人不一致，需人工处理"
            return renewal_repo.update(r["id"], {
                "status": "PAYMENT_EXCEPTION", "trade_status": "TRADE_SUCCESS",
                "trade_no": trade_no, "paid_at": now, "raw_query": raw,
                "failure_reason": reason,
            })
        # 先更新原订单；return 续租后恢复 using，状态变更会自动同步支付宝。
        update_order(o["id"], {
            "end_date": r["new_end_date"], "days": int(r.get("new_total_days") or 0),
            "amount": round_yuan(float(o.get("amount") or 0) + float(r.get("quoted_amount") or 0)),
            "original_amount": round_yuan(float(o.get("original_amount") or o.get("amount") or 0)
                                          + float(r.get("quoted_amount") or 0)),
            "status": "using", "renewed_at": now,
        }, sync_reason="renewal_completed")
        # 先告知支付宝发生了续租，再落回持续的“租赁中”状态。
        try:
            from app.order_sync import sync_order
            sync_order(o["id"], reason="renewal_relet", status_override="RELET")
            sync_order(o["id"], reason="renewal_back_in_lease")
        except Exception as e:
            logger.warning("renewal order sync failed oid=%s: %s", o["id"], e)
        return renewal_repo.update(r["id"], {
            "status": "COMPLETED", "trade_status": "TRADE_SUCCESS",
            "trade_no": trade_no, "paid_at": now, "completed_at": now,
            "raw_query": raw, "failure_reason": "",
        })


@bp.post("/renewals/<rid>/query")
def renewal_query(rid):
    r = renewal_repo.get(rid)
    if not r:
        return fail(404, "续租单不存在")
    if r.get("user_id") != current_user_id():
        return fail(403, "无权操作")
    if r.get("status") == "COMPLETED":
        return ok({"completed": True, "renewal": _renewal_view(r)})
    try:
        from app.alipay_client import get_client
        q = get_client().trade_query(out_trade_no=r.get("out_trade_no"))
        trade_status = q.get("trade_status") or ""
        renewal_repo.update(rid, {"trade_status": trade_status, "raw_query": q})
        if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            r = complete_renewal(r["out_trade_no"], trade_no=q.get("trade_no") or "", raw=q) or r
        else:
            r = renewal_repo.get(rid) or r
        return ok({"completed": r.get("status") == "COMPLETED", "renewal": _renewal_view(r)})
    except Exception as e:
        return fail(1, f"查询支付结果失败：{e}")


# 给用户端订单详情页展示历史扣款记录用：
# 只回显实际发生过资金变动的记录（TRADE_SUCCESS / TRADE_FINISHED），
# 失败尝试、操作员、阿里原始响应等内部信息不暴露给 C 端。
_USER_VISIBLE_TRADE_STATUS = frozenset({"TRADE_SUCCESS", "TRADE_FINISHED"})
_REASON_LABEL_FOR_USER = {
    "RENT_SERVICE":         "租金/服务费",
    "OVERDUE_PENALTY":      "逾期违约金",
    "DAMAGE_LOSS":          "损坏/丢失赔偿",
    "USER_CONFIRMED_OTHER": "其他费用",
}


@bp.get("/<oid>/logistics")
def order_logistics_routes(oid):
    """订单物流轨迹（用户端）。走缓存，?refresh=1 强制回源（下拉刷新用）。

    不支持查轨迹的单（非顺丰 / 未配顺丰 / 还没发货）也返回 200，
    只是 supported=false——前端据此决定展不展开轨迹区，不需要区分错误。
    """
    from app import order_logistics
    uid = current_user_id()
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != uid:
        return fail(403, "无权查看")

    force = (request.args.get("refresh") or "").strip() in ("1", "true")
    try:
        return ok(order_logistics.fetch(o, force=force))
    except Exception as e:
        # 物流查不到不该让整个详情页报错，返回空轨迹让页面照常渲染
        logger.warning("order_logistics oid=%s err: %s", oid, e)
        return ok({"supported": False, "routes": [], "synced_at": 0,
                   "cached": False, "signed_at": "", "error": "物流信息暂时查询不到",
                   "company": "", "waybill_no": (o.get("logistics_no") or "")})


@bp.get("/<oid>/charges")
def order_charges(oid):
    """订单的历史扣款记录（用户端可见）。"""
    from app.storage.repos import trade_repo
    uid = current_user_id()
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != uid:
        return fail(403, "无权查看")

    items = [t for t in trade_repo.list(order_id=oid)
             if t.get("status") in _USER_VISIBLE_TRADE_STATUS]
    items.sort(key=lambda x: -int(x.get("paid_at") or x.get("created_at") or 0))

    rows = []
    total = 0.0
    for t in items:
        amount = float(t.get("receipt_amount") or t.get("amount") or 0)
        total += amount
        paid_ts = int(t.get("paid_at") or t.get("created_at") or 0)
        refunded = float(t.get("refunded_amount") or 0)
        refundable = round(max(0.0, amount - refunded), 2)
        ap = t.get("refund_apply") or {}
        rows.append({
            "id":            t.get("id"),
            "amount":        round(amount, 2),
            "amount_text":   f"{amount:.2f}",
            "subject":       t.get("subject") or "",
            "reason_type":   t.get("reason_type") or "",
            "reason_label":  _REASON_LABEL_FOR_USER.get(t.get("reason_type") or "", "扣款"),
            "reason_detail": t.get("reason_detail") or "",
            "paid_at":       paid_ts,
            "paid_at_text":  (time.strftime("%Y-%m-%d %H:%M", time.localtime(paid_ts))
                              if paid_ts else ""),
            # 退款相关：让小程序据此决定显示"申请退款" / "审核中" / "已退款 ¥xx"
            "refunded_amount":   round(refunded, 2),
            "refundable_amount": refundable,
            "refund_apply": {
                "status":          ap.get("status") or "",
                "reason":          ap.get("reason") or "",
                "applied_at":      int(ap.get("applied_at") or 0),
                "applied_at_text": (time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(int(ap.get("applied_at") or 0))
                ) if ap.get("applied_at") else ""),
                "rejected_reason": ap.get("rejected_reason") or "",
                "reviewed_at":     int(ap.get("reviewed_at") or 0),
                "reviewed_at_text": (time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(int(ap.get("reviewed_at") or 0))
                ) if ap.get("reviewed_at") else ""),
            } if ap else {"status": ""},
        })
    return ok({
        "list":             rows,
        "count":            len(rows),
        "total_amount":     round(total, 2),
        "total_amount_text": f"{total:.2f}",
    })


@bp.post("/<oid>/charges/<otn>/refund-apply")
def order_charge_refund_apply(oid, otn):
    """用户对某一笔扣款发起退款申请（不立即退款，等商家在后台审核）。

    Body:
      reason  必填，退款理由（10–500 字）

    校验：
      - 扣款属于本订单 & 本订单属于当前用户
      - 扣款状态为 TRADE_SUCCESS / TRADE_FINISHED（已实际收款的才能申）
      - 该扣款还有剩余可退金额（refundable_amount > 0）
      - 当前没有 PENDING 状态的申请（重复申请直接拒）

    审核通过：芝麻信用要求商家发起 alipay.trade.refund 实际退款（在后台审核接口里做）。
    审核驳回：把 status 改为 REJECTED，附驳回理由，允许用户重新申请。
    """
    from app.storage.repos import trade_repo
    uid = current_user_id()
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != uid:
        return fail(403, "无权操作")

    t = trade_repo.get(otn)
    if not t:
        return fail(404, "扣款记录不存在")
    if t.get("order_id") != oid:
        return fail(403, "扣款不属于该订单")
    if t.get("status") not in _USER_VISIBLE_TRADE_STATUS:
        return fail(40050, "该扣款尚未实际收款，无法申请退款")

    paid     = float(t.get("amount") or 0)
    refunded = float(t.get("refunded_amount") or 0)
    refundable = round(paid - refunded, 2)
    if refundable <= 0:
        return fail(40051, "该扣款已全部退款，无可申请金额")

    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    if len(reason) < 5:
        return fail(40052, "退款理由至少 5 个字")
    if len(reason) > 500:
        return fail(40053, "退款理由不超过 500 字")

    cur = t.get("refund_apply") or {}
    if cur.get("status") == "PENDING":
        return fail(40054, "已有正在审核中的退款申请，请耐心等待")

    now = int(time.time())
    new_apply = {
        "status":          "PENDING",
        "reason":          reason,
        "applied_at":      now,
        "reviewed_at":     0,
        "reviewer":        "",
        "rejected_reason": "",
        # 用户填写时按"剩余可退"申请；实际退款金额以商家审核时为准
        "apply_amount":    refundable,
        "refund_out_request_no": "",
    }
    trade_repo.update(otn, {"refund_apply": new_apply})
    return ok({
        "status":         "PENDING",
        "applied_at":     now,
        "apply_amount":   refundable,
        "review_hint":    "退款需 2 个工作日内审核，如需加急请拨打客服电话 400-000-0000",
    }, "已提交退款申请，等待商家审核")


# ---------- 首期租金支付 ----------
def _rent_trade_no(order: dict) -> str:
    """首期租金交易号固定为订单号 + R。

    同一订单重复点击只会复用同一笔支付宝交易，不会重复收款。
    """
    return (order.get("rent_out_trade_no") or f"{order['id']}R").strip()


def refund_initial_rent(order: dict, reason: str = "租赁订单取消") -> tuple[bool, str]:
    """取消已付租金订单时原路全额退租金。固定 out_request_no 保证重试幂等。"""
    if not order.get("rent_paid_at") or order.get("rent_refunded_at"):
        return True, ""
    amount = float(order.get("amount") or 0)
    # 0 元租金单（租押分离）的 rent_paid_at 是"无租可收"的标记，背后没有真实交易，
    # 也就没有可退的钱。这里必须放行：判失败会让取消流程（用户取消 / 商家同意取消 /
    # 后台强制取消）全部中止，订单卡在 audit / pending_cancel。
    if amount <= 0:
        order_repo.update(order["id"], {
            "rent_refunded_at":     int(time.time()),
            "rent_refunded_amount": 0.0,
            "rent_refund_error":    "",
        })
        return True, ""
    out_request_no = (order.get("rent_refund_request_no") or f"RF{order['id']}RENT")[:64]
    from app.alipay_client import get_client
    try:
        resp = get_client().trade_refund(
            refund_amount=amount,
            out_trade_no=_rent_trade_no(order),
            out_request_no=out_request_no,
            refund_reason=reason,
        )
        success = str(resp.get("code") or "") == "10000" and str(resp.get("fund_change") or "").upper() == "Y"
        if not success and str(resp.get("code") or "") == "10000":
            q = get_client().trade_refund_query(
                out_request_no=out_request_no, out_trade_no=_rent_trade_no(order),
            )
            success = (q.get("refund_status") or "").upper() == "REFUND_SUCCESS"
            if success:
                resp = {"refund": resp, "query": q}
        patch = {
            "rent_refund_request_no": out_request_no,
            "rent_refund_raw": resp,
            "rent_refund_error": "" if success else (resp.get("sub_msg") or resp.get("msg") or "退款结果未确认"),
        }
        if success:
            patch.update({"rent_refunded_at": int(time.time()), "rent_refunded_amount": amount})
        order_repo.update(order["id"], patch)
        return success, patch["rent_refund_error"]
    except Exception as e:
        order_repo.update(order["id"], {
            "rent_refund_request_no": out_request_no, "rent_refund_error": str(e)[:500],
        })
        return False, str(e)


def complete_initial_rent(out_trade_no: str, *, trade_no: str = "", raw: dict | None = None) -> dict | None:
    """首期租金支付成功的唯一业务出口：pay → audit，回调与主动查询共用。"""
    if not out_trade_no.endswith("R"):
        return None
    oid = out_trade_no[:-1]
    o = order_repo.get(oid)
    if not o or _rent_trade_no(o) != out_trade_no:
        return None
    if o.get("status") == "cancelled":
        return update_order(oid, {
            "rent_trade_status": "PAYMENT_EXCEPTION",
            "rent_payment_error": "订单取消与租金支付同时发生，需原路退款",
            "rent_trade_no": trade_no,
            "rent_payment_raw": raw or {},
        })
    if o.get("status") != "pay":
        return o

    raw = raw or {}
    try:
        paid_amount = float(raw.get("total_amount") or raw.get("receipt_amount") or o.get("amount") or 0)
    except (TypeError, ValueError):
        paid_amount = 0
    expected = float(o.get("amount") or 0)
    if abs(paid_amount - expected) > 0.001:
        return update_order(oid, {
            "rent_trade_status": "PAYMENT_EXCEPTION",
            "rent_payment_error": "支付金额与订单租金不一致，需人工核对",
            "rent_trade_no": trade_no,
            "rent_payment_raw": raw,
        })

    now = int(time.time())
    return update_order(oid, {
        "status": "audit",
        "rent_trade_status": "TRADE_SUCCESS",
        "rent_trade_no": trade_no,
        "rent_paid_at": now,
        "rent_payment_error": "",
        "rent_payment_raw": raw,
    }, sync_reason="initial_rent_paid")


@bp.post("/<oid>/rent/pay")
def initial_rent_pay(oid):
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != current_user_id():
        return fail(403, "无权操作该订单")
    if o.get("status") == "audit" and o.get("rent_paid_at"):
        return ok({"already_paid": True, "order": _enrich(o)}, "租金已支付")
    if o.get("status") != "pay":
        return fail(1, "当前订单已不可支付租金")
    amount = float(o.get("amount") or 0)
    if amount <= 0:
        return fail(1, "订单租金异常，请联系客服")

    out_trade_no = _rent_trade_no(o)
    order_repo.update(oid, {
        "rent_out_trade_no": out_trade_no,
        "rent_trade_status": "WAIT_BUYER_PAY",
    })
    try:
        from app.alipay_client import get_client
        pay = get_client().trade_create(
            out_trade_no, amount, f"{o.get('product_name') or '租赁订单'} - 租金",
            buyer_id=current_user_id(),
            body=f"订单 {oid} 首期租金",
        )
        return ok({**pay, "out_trade_no": out_trade_no})
    except Exception as e:
        order_repo.update(oid, {"rent_trade_status": "FAILED", "rent_payment_error": str(e)[:500]})
        return fail(1, f"创建租金支付失败：{e}")


@bp.post("/<oid>/rent/query")
def initial_rent_query(oid):
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != current_user_id():
        return fail(403, "无权操作该订单")
    if o.get("rent_paid_at"):
        return ok({"is_paid": True, "order": _enrich(o)})
    try:
        from app.alipay_client import get_client
        q = get_client().trade_query(out_trade_no=_rent_trade_no(o))
        trade_status = (q.get("trade_status") or "").upper()
        order_repo.update(oid, {"rent_trade_status": trade_status, "rent_payment_raw": q})
        if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            o = complete_initial_rent(
                _rent_trade_no(o), trade_no=q.get("trade_no") or "", raw=q,
            ) or o
        return ok({"is_paid": bool(o.get("rent_paid_at")), "trade_status": trade_status, "order": _enrich(o)})
    except Exception as e:
        return fail(1, f"查询租金支付结果失败：{e}")


# ---------- 创建 / 取消 ----------
@bp.post("")
def create_order():
    body = request.get_json(silent=True) or {}
    pid = body.get("product_id")
    days = int(body.get("days") or 7)
    # 用机天数硬约束（前端日历也按此提示，这里再兜一层防绕过）
    if days < MIN_RENT_DAYS:
        return fail(40010, f"最少租期 {MIN_RENT_DAYS} 天（不含物流期）")
    # 日历选租期带来的附加履约信息（小程序新版下单会传；老入口不传则留空）
    start_date = (body.get("start_date") or "").strip()
    end_date   = (body.get("end_date") or "").strip()
    ship_days  = int(body.get("ship_days") or 0)
    # 用户备注（确认订单页填）：截断到 200 字，避免超长文本撑爆订单列表/详情展示。
    # 不做内容校验——这是用户写给商家的话，商家自己判断。
    user_remark = (body.get("user_remark") or "").strip()[:200]
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")

    # 上架校验：非 on（下架 off / 草稿 draft）一律不可下单，与库存无关
    # 列表只展示 on，但直连 product_id 调接口能绕过，这里硬堵
    if (p.get("status") or "") != "on":
        return fail(40023, "该商品已下架，无法下单")

    # SKU 解析：价格 / 押金 / 库存的真相在 SKU 层，正常商品都恒有至少一个 SKU。
    on_sale_skus = [
        s for s in sku_repo.list(product_id=p["id"])
        if (s.get("status") or "on") == "on"
    ]
    sku = None
    if on_sale_skus:
        raw_sku_id = body.get("sku_id")
        try:
            sku_id = int(raw_sku_id or 0)
        except (TypeError, ValueError):
            sku_id = 0
        sku = next((s for s in on_sale_skus if s.get("id") == sku_id), None)
        if not sku:
            if len(on_sale_skus) == 1 and not raw_sku_id:
                # 只有一个 SKU 时价格唯一、不存在歧义 → 不传 sku_id 也放行。
                # 这条保证了老版本小程序（不认识 SKU）在单 SKU 商品上照常下单。
                sku = on_sale_skus[0]
            else:
                # 多 SKU 却没指定（或指定了不存在的）：宁可报错也不替用户猜，
                # SKU 之间押金/租金不同，猜错就是按错的价扣钱。
                return fail(40024, "请选择 SKU 后再下单")

    # 下面这些字段一律从 spec 取：正常是 SKU 行；SKU 被删空的极端情况退回商品行
    spec = sku or p

    # 库存校验：库存 <= 0 禁止下单（后台把库存调 0 即等于下架不可租）
    if int(spec.get("stock") or 0) <= 0:
        return fail(40022, "该 SKU 库存不足，暂时无法下单" if sku else "该商品库存不足，暂时无法下单")

    # 押金必填硬约束：避免历史数据漏配押金导致 deposit_freeze=0 让用户白嫖
    deposit_freeze = float(spec.get("deposit_amount") or 0)
    if deposit_freeze <= 0:
        return fail(40020, "该商品押金未配置，请联系客服")

    uid = current_user_id()
    addr_id = body.get("address_id")
    if addr_id:
        # 确认订单页会让用户选地址并回传 address_id。它来自客户端，必须校验归属，
        # 否则传别人的 id 就能把本单的收货快照写成别人的姓名/电话/地址。
        # 不属于当前用户时直接拒绝，而不是悄悄回落到默认地址——那会让用户
        # 以为发往 A、实际发往 B。
        addr = address_repo.get(addr_id)
        if not addr or addr.get("user_id") != uid:
            return fail(40002, "收货地址不存在或不属于当前用户")
    else:
        addr = _default_address(uid)
    if not addr:
        return fail(40001, "请先添加收货地址")

    # 分段租金：用商品当前 price_tiers 计算实付，并把 tiers 快照存进订单，
    # 避免后续运营改价影响历史订单展示与对账。
    tiers = normalize_tiers(spec.get("price_tiers") or [{"from": 1, "price": p.get("price") or 0}])
    # 零价兜底：与商品详情/列表同口径。allow_zero_rent 关时把 0 档当兜底值计费
    # （防 0 元白嫖）；开时（租押分离）保留 0，允许 0 元租金单。
    from app.settings import get as _setting_get
    allow_zero_rent = bool(_setting_get("allow_zero_rent", False))
    if not allow_zero_rent:
        try:
            _fb = float(_setting_get("min_price_floor", 20) or 0)
        except (TypeError, ValueError):
            _fb = 20.0
        tiers = substitute_zero_tiers(tiers, _fb)
    original_amount = calc_amount(days, tiers)
    # 正常租赁模式禁止 0 元下单（兜底后仍为 0 说明真没配租金）；
    # 租押分离模式允许 0 元租金（仅冻押金担保）。
    if not allow_zero_rent and original_amount <= 0:
        return fail(40021, "该商品租金未配置，请联系客服")

    # 优惠券：满 threshold 减 discount。仅当用户传 user_coupon_id 时启用。
    # 校验 ownership + 状态 + 门槛；通过则核销并把抵扣信息快照写订单。
    user_coupon_id = body.get("user_coupon_id")
    coupon_snapshot = {
        "coupon_id": 0,
        "user_coupon_id": 0,
        "coupon_name": "",
        "coupon_threshold": 0.0,
        "coupon_discount": 0.0,
        "discount_amount": 0.0,
    }
    amount = original_amount
    used_uc = None
    if user_coupon_id:
        used_uc = user_coupon_repo.get(user_coupon_id)
        if not used_uc or used_uc.get("user_id") != uid:
            return fail(40030, "优惠券不存在或不属于当前用户")
        if not user_coupon_is_usable(used_uc):
            return fail(40031, "优惠券已使用或已过期")
        if not applicable_to_amount(used_uc, original_amount):
            return fail(40032, f"订单金额未达到满 {used_uc.get('threshold')} 元门槛")
        discount = calc_discount(used_uc, original_amount)
        # 券面额可能带小数（如满 300 减 5.5），扣完再取整一次，
        # 保证「实付租金」也是整数——这是真正入账、也是用户看到的数
        amount = round_yuan(max(0.0, original_amount - discount))
        coupon_snapshot.update({
            "coupon_id": int(used_uc.get("coupon_id") or 0),
            "user_coupon_id": used_uc["id"],
            "coupon_name": used_uc.get("name", ""),
            "coupon_threshold": float(used_uc.get("threshold") or 0),
            "coupon_discount": float(used_uc.get("discount") or 0),
            "discount_amount": discount,
        })

    # 方案 A：押金 + 租金一次综合授权。授权成功后后端立即把租金
    # 从授权池转为实际支付，剩余押金继续免押/冻结担保。
    includes_rent = True
    freeze_amount = round(deposit_freeze + amount, 2)

    record = {
        "id": "O" + uuid.uuid4().hex[:12].upper(),
        "user_id": uid,
        "product_id": p["id"],
        "product_name": p["name"],
        # SKU 快照：sku_id 用于扣库存/对账，sku_name 用于各端展示。
        # 极端情况（商品一个 SKU 都没有）落 0 / 空串，前端据此不显示 SKU 行。
        "sku_id":   sku["id"] if sku else 0,
        "sku_name": (sku.get("name") or "") if sku else "",
        "price_per_day": first_unit_price(tiers),
        "days": days,
        "amount": amount,
        "original_amount": original_amount,
        "price_tiers": tiers,
        "start_date": start_date,
        "end_date": end_date,
        "ship_days": ship_days,
        "user_remark": user_remark,
        "deposit_freeze":        deposit_freeze,
        "freeze_amount":         freeze_amount,
        "freeze_includes_rent":  includes_rent,
        "credit": p.get("credit", False),
        "status": "audit",
        "address_id": addr["id"],
        "address_snapshot": {
            "receiver_name": addr["receiver_name"],
            "receiver_phone": addr["receiver_phone"],
            "full": f"{addr['province']} {addr['city']} {addr['district']} {addr['detail']}",
        },
        "lock_until": None,
        "certify_id": None,
        **coupon_snapshot,
    }
    created = order_repo.create(record)

    # 订单写库成功后核销券（订单失败则不动券，避免券白白消耗）
    if used_uc:
        user_coupon_repo.update(used_uc["id"], {
            "status": "used",
            "order_id": created["id"],
            "used_at": int(time.time()),
        })

    # 异步同步到支付宝订单中心（失败不抛错，会落 notify_log）
    try:
        from app.order_sync import sync_order
        sync_order(created["id"], reason="create")
    except Exception:
        pass

    return ok(created, "下单成功")


@bp.post("/<oid>/cancel")
def cancel(oid):
    """用户自助取消订单。按当前状态分流：
      pay            → cancelled（尚未收租金、尚未发起免押）
      audit          → cancelled；发起过冻结的先向支付宝对账，已冻结的先解冻再取消
                       （用户可能付款途中取消，"无冻结物"不再必然成立）
      send           → 提交取消申请 → pending_cancel（待商家审核）
                       商家在后台同意后才会调 unfreeze 真正解冻+取消
      pending_cancel → 已提交过申请，幂等返回
      其他状态       → 拒绝（要走客服线下流程）
    """
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "").strip()
    status = o.get("status")
    now = int(time.time())

    if status == "pay":
        # 发起过租金支付时先向支付宝对账，避免回调延迟时误取消已付款订单。
        if (o.get("rent_out_trade_no") or "").strip():
            try:
                from app.alipay_client import get_client
                q = get_client().trade_query(out_trade_no=_rent_trade_no(o))
                if (q.get("trade_status") or "").upper() in ("TRADE_SUCCESS", "TRADE_FINISHED"):
                    complete_initial_rent(
                        _rent_trade_no(o), trade_no=q.get("trade_no") or "", raw=q,
                    )
                    return fail(1, "租金已支付，订单不能直接取消；如需取消请联系客服")
            except Exception as e:
                return fail(1, f"正在核对租金支付结果，暂时无法取消：{e}")
        updated = update_order(oid, {
            "status": "cancelled", "cancel_reason": reason,
            "cancelled_at": now,
        }, sync_reason="cancel_before_rent_paid")
        _refund_coupon_if_any(o)
        return ok(updated, "订单已取消")

    if status == "audit":
        # 对账/解冻失败不阻塞取消：迟到的冻结成功通知会命中 notify 侧
        # "已取消订单自动解冻"兜底，资金不会悬挂
        if int(o.get("alipay_freeze_attempts") or 0) > 0:
            try:
                from app.routes.alipay import (
                    query_active_freeze, is_frozen,
                    dispatch_auto_unfreeze, freeze_pool_amount,
                )
                res = query_active_freeze(o)
                if is_frozen(res):
                    dispatch_auto_unfreeze(
                        o,
                        (res.get("auth_no") or o.get("alipay_auth_no") or "").strip(),
                        freeze_pool_amount(o, res.get("amount")),
                        reason="user_cancel_frozen",
                    )
            except Exception:
                pass
        refunded, refund_err = refund_initial_rent(o)
        if not refunded:
            return fail(1, f"租金退款未完成，已中止取消：{refund_err}")
        updated = update_order(oid, {"status": "cancelled", "cancelled_at": now},
                               sync_reason="user_cancel")
        _refund_coupon_if_any(o)
        return ok(updated, "已取消")

    if status == "send":
        updated = update_order(oid, {
            "status": "pending_cancel",
            "cancel_requested_at": now,
            "cancel_reason": reason,
        }, sync_reason="request_cancel")
        return ok(updated, "取消申请已提交，等待商家审核")

    if status == "pending_cancel":
        return ok(o, "取消申请已在审核中")

    return fail(40050, "订单已进入履约阶段，请联系客服处理")


# ---------- 用户寄回归还 ----------
@bp.get("/couriers")
def couriers_public():
    """支持的快递公司列表（用户端归还表单下拉用）。"""
    from app import logistics
    return ok({"list": logistics.supported_list()})


@bp.post("/<oid>/return-ship")
def return_ship(oid):
    """用户填写寄回快递信息 → return_inspecting，等商家核验。

    允许的来源状态：using（提前归还）/ return（到期归还）/ overdue（逾期归还）。
    入参：{logistics_company, logistics_no}；运单号大小写空白会被规范化。
    """
    from app import logistics
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("user_id") != current_user_id():
        return fail(403, "无权操作")

    status = o.get("status")
    if status not in _RETURN_SHIP_ALLOWED:
        cur_label = _USER_STATUS_LABEL.get(status, status)
        return fail(1, f"当前状态「{cur_label}」不能发起归还")

    body = request.get_json(silent=True) or {}
    logistics_no = logistics.normalize_no(body.get("logistics_no") or "")
    company_input = (body.get("logistics_company") or "").strip().upper()
    # 前端把用户点选的 segment 文字（如"顺丰速运"）一起带过来；原样落库供展示
    company_name_input = (body.get("logistics_company_name") or "").strip()
    if not logistics_no:
        return fail(1, "请填写运单号")
    if not company_input or not logistics.is_supported(company_input):
        return fail(1, "请选择有效的快递公司（目前仅支持顺丰 SF / 京东 JD）")

    # 运单号若能被自动识别出快递公司，必须与用户所选一致，避免选错快递公司导致核验找不到包裹
    detected = logistics.identify(logistics_no)
    if detected.code != "unknown" and detected.code != company_input:
        return fail(
            1,
            f"运单号「{logistics_no}」看起来是{detected.name}的格式，"
            f"与所选快递公司不一致，请核对",
        )

    now = int(time.time())
    updated = update_order(oid, {
        "status":                   "return_inspecting",
        "return_logistics_company": company_input,
        "return_logistics_company_name": company_name_input,
        "return_logistics_no":      logistics_no,
        "returned_at":              now,
    }, sync_reason="return_ship")
    return ok(_enrich(updated), "已提交寄回信息，等待商家核验")


def _refund_coupon_if_any(o: dict) -> None:
    """订单取消时退回优惠券（恢复到可用状态）"""
    uc_id = int(o.get("user_coupon_id") or 0)
    if not uc_id:
        return
    try:
        user_coupon_repo.update(uc_id, {
            "status": "unused",
            "order_id": 0,
            "used_at": 0,
        })
    except Exception:
        pass


# ---------- 状态机推进（供 alipay.notify / query 调用） ----------
# 所有写 status 的 update 一律走 update_order，由其内部拦截器自动 sync 到支付宝订单中心。
def order_id_from_out_order_no(out_order_no: str) -> str:
    """支付宝授权订单号 → 本地订单号。

    订单号格式为 'O' + 12 位大写 16 进制，字符集仅 [0-9A-F]，**不含下划线**。
    据此把"按尝试递增"的 out_order_no 还原成订单号：
      - 历史/首次冻结 out_order_no == oid（无 '_'）→ split 原样返回；
      - 回退/重试冻结 out_order_no == oid_A2     → 截掉 '_A2' 后缀还原 oid。
    对裸号和带后缀号都成立，故老回调老数据天然兼容。
    """
    return (out_order_no or "").split("_", 1)[0]


def _capture_initial_rent_from_auth(order: dict) -> tuple[bool, str]:
    """综合授权成功后，从授权池立即转支付首期租金。

    商户交易号固定，重复 notify/query 只会查询或复用同一笔交易。
    只有支付宝明确返回 TRADE_SUCCESS/FINISHED 才允许订单进入待发货；
    0 元租金单（租押分离）没有交易可发起，直接按"已结清"放行。
    """
    from app.alipay_client import get_client
    from app.storage.repos import trade_repo

    oid = order.get("id") or ""
    amount = float(order.get("amount") or 0)
    auth_no = (order.get("alipay_auth_no") or "").strip()
    if not oid:
        return False, "订单号缺失"
    if order.get("rent_paid_at"):
        return True, ""
    # 租押分离模式（settings.allow_zero_rent）允许 0 元租金单：只冻押金担保，
    # 压根没有可转支付的租金。必须当作"已结清"放行——否则综合授权成功后这里
    # 一直判失败，transition_freeze_done 掉头返回，订单永远停在 audit（待免押）。
    if amount <= 0:
        order_repo.update(oid, {
            "rent_trade_status":  "NO_RENT",
            "rent_paid_at":       int(time.time()),
            "rent_payment_error": "",
        })
        return True, ""
    if not auth_no:
        return False, "综合授权成功但缺少 auth_no"

    out_trade_no = (order.get("rent_out_trade_no") or f"{oid}R")[:64]
    now = int(time.time())
    order_repo.update(oid, {
        "rent_out_trade_no": out_trade_no,
        "rent_trade_status": "PROCESSING",
        "rent_capture_attempts": int(order.get("rent_capture_attempts") or 0) + 1,
        # 供定时重试算退避间隔；也让运营一眼看到"最后一次尝试是什么时候"
        "rent_capture_last_at": now,
    })

    # 先查询：回调重放或上次“扣款成功但本地超时”时不再发起新扣款。
    query = None
    try:
        query = get_client().trade_query(out_trade_no=out_trade_no)
    except Exception:
        pass

    trade_status = ((query or {}).get("trade_status") or "").upper()
    raw_pay = None
    # auth_trade_pay 抛出的原始异常文本（含支付宝 code/sub_code/sub_msg），
    # 是判断"为什么扣不动"的唯一线索，无条件留痕。
    pay_err = ""
    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        try:
            raw_pay = get_client().auth_trade_pay(
                out_trade_no=out_trade_no,
                total_amount=amount,
                subject=f"【租金/服务费】{order.get('product_name') or '租赁商品'}",
                auth_no=auth_no,
                auth_confirm_mode="NOT_COMPLETE",
                order_id=oid,
                product_id=order.get("product_id") or None,
                product_name=order.get("product_name") or None,
                body="综合授权成功后自动收取首期租金",
            )
        except Exception as e:
            # 立刻落库，不要等"补查也炸了"才记：trade_query 对「交易不存在」只返回
            # code=40004 的 body 而不抛异常（alipay_client.trade_query 走裸 execute），
            # 所以下面那个 try 几乎必然成功，以前 e 就在这里被彻底吞掉了。
            pay_err = str(e)[:500]
            logger.warning("rent capture: 订单 %s auth_trade_pay 失败: %s", oid, pay_err)
            order_repo.update(oid, {"rent_capture_last_error": pay_err})
            # 同步响应失败也可能已落交易，再 query 一次才下结论。
            try:
                query = get_client().trade_query(out_trade_no=out_trade_no)
                trade_status = (query.get("trade_status") or "").upper()
            except Exception:
                order_repo.update(oid, {"rent_trade_status": "FAILED", "rent_payment_error": pay_err})
                return False, pay_err
        if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            try:
                query = get_client().trade_query(out_trade_no=out_trade_no)
                trade_status = (query.get("trade_status") or "").upper()
            except Exception:
                trade_status = ((raw_pay or {}).get("trade_status") or "").upper()

    if not trade_repo.get(out_trade_no):
        trade_repo.create({
            "id": out_trade_no, "order_id": oid, "amount": amount,
            "subject": "首期租金", "reason_type": "RENT_SERVICE",
            "reason_detail": "综合授权后自动转支付", "auth_no": auth_no,
            "auth_confirm_mode": "NOT_COMPLETE", "status": trade_status or "PROCESSING",
            "raw_pay": raw_pay or {}, "raw_query": query or {},
        })
    else:
        trade_repo.update(out_trade_no, {
            "status": trade_status or "PROCESSING", "raw_pay": raw_pay or {}, "raw_query": query or {},
        })

    if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        trade_no = ((query or {}).get("trade_no") or (raw_pay or {}).get("trade_no") or "")
        order_repo.update(oid, {
            "rent_trade_status": trade_status, "rent_trade_no": trade_no,
            "rent_paid_at": now, "rent_payment_error": "", "rent_payment_raw": query or raw_pay or {},
            # 中途失败过、最终扣成的单：清掉旧报错，免得后台一直挂着历史错误
            "rent_capture_last_error": "",
        })
        trade_repo.update(out_trade_no, {"status": trade_status, "trade_no": trade_no, "paid_at": now})
        return True, ""

    err = f"租金转支付未成功，当前状态：{trade_status or '未知'}"
    if pay_err:
        err = f"{err}；支付宝返回：{pay_err}"
    order_repo.update(oid, {
        "rent_trade_status": trade_status or "PROCESSING", "rent_payment_error": err[:500],
    })
    return False, err


def transition_freeze_done(out_order_no: str) -> dict | None:
    """综合授权成功 → 自动收租金 → audit → send。
    租金未确认到账时严禁扣库存和进待发货。
    """
    oid = order_id_from_out_order_no(out_order_no)
    o = order_repo.get(oid)
    if not o or o.get("status") != "audit":
        return o
    captured, err = _capture_initial_rent_from_auth(o)
    if not captured:
        logger.warning("freeze_done: 订单 %s 授权成功但租金转支付未完成: %s", oid, err)
        return order_repo.get(oid)
    o = order_repo.get(oid) or o
    # 综合授权 + 租金收款均成功 = 设备正式被占用，此刻才扣 1 库存。
    # 放在这个 transition 里而非下单时：① 只有真正免押成功的单才占库存，未完成免押的
    # 不挤占；② 本函数已用 status==audit 做了幂等闸，支付宝重发 freeze 通知不会重复扣。
    # 归还/取消不在此自动加回，由后台人工调整库存（按业务约定）。
    # 有 SKU 的订单扣 SKU 库存，没有的扣商品库存。两边都走同一个原子条件更新，
    # 扣不动（余量已为 0）只告警不阻断发货，与改造前行为一致。
    sku_id = int(o.get("sku_id") or 0)
    pid = o.get("product_id")
    if sku_id:
        left = sku_repo.try_decrement(sku_id, "stock", by=1, floor=0)
        if left is None:
            import logging
            logging.getLogger(__name__).warning(
                "freeze_done: 订单 %s SKU %s(%s) 免押成功但库存已为 0，未扣减（请后台核对）",
                oid, sku_id, o.get("sku_name") or "",
            )
        # SKU 是销量的唯一数据源；一张免押成功的订单计 1 件。
        # status==audit 是幂等闸，顺序重放支付宝回调不会重复累加。
        sku_repo.increment(sku_id, "sales", by=1)
    elif pid:
        left = product_repo.try_decrement(pid, "stock", by=1, floor=0)
        if left is None:
            import logging
            logging.getLogger(__name__).warning(
                "freeze_done: 订单 %s 商品 %s 免押成功但库存已为 0，未扣减（请后台核对）",
                oid, pid,
            )
        # 无 SKU 历史数据的极端兜底。
        product_repo.increment(pid, "sales", by=1)
    return update_order(oid, {
        "status": "send",
        "send_at": int(time.time()),
    }, sync_reason="freeze_done")


def transition_unfreeze_done(out_order_no: str) -> dict | None:
    """解冻成功 → 不同来源走不同终态：
      pending_cancel              → cancelled（商家同意取消、支付宝异步确认解冻完成）
                                    同时退优惠券
      return / overdue / using    → done（正常归还的解冻）

    幂等：支付宝可能重发通知；终态再调一次只命中 if 之外的早退分支，不会重复退券/重复 sync。
    """
    oid = order_id_from_out_order_no(out_order_no)
    o = order_repo.get(oid)
    if not o:
        return None
    status = o.get("status")
    if status == "pending_cancel":
        refunded, refund_err = refund_initial_rent(o)
        if not refunded:
            order_repo.update(oid, {"rent_refund_error": refund_err})
            return o
        updated = update_order(oid, {
            "status":       "cancelled",
            "cancelled_at": int(time.time()),
            # 后台强制取消（admin_force）在下发解冻时已写 cancelled_by，不覆盖；
            # 用户申请-商家同意的链路没写过，落默认 admin_approve
            "cancelled_by": o.get("cancelled_by") or "admin_approve",
        }, sync_reason="admin_cancel_approve")
        _refund_coupon_if_any(o)
        return updated
    if status in ("return", "overdue", "using", "return_inspecting"):
        return update_order(oid, {
            "status":      "done",
            "returned_at": o.get("returned_at") or int(time.time()),
        }, sync_reason="return_done")
    return o


def transition_auth_pay_done(out_order_no: str) -> dict | None:
    """预授权转支付成功（押金/逾期租金从冻结额度划走）→ using/overdue → return"""
    oid = order_id_from_out_order_no(out_order_no)
    o = order_repo.get(oid)
    if not o:
        return None
    if o.get("status") in ("using", "overdue"):
        return update_order(oid, {"status": "return"},
                            sync_reason="auth_pay_done")
    return o


def transition_trade_paid(out_trade_no: str) -> dict | None:
    """普通交易支付成功；先分流首期租金，再兼容续租单。"""
    return complete_initial_rent(out_trade_no) or complete_renewal(out_trade_no)


def transition_trade_refunded(out_trade_no: str) -> dict | None:
    """退款成功。当前仅查找日志占位。"""
    return order_repo.get(out_trade_no)
