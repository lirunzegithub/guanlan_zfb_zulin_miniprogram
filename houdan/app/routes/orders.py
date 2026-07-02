"""订单接口（全 SQLite 持久化版）"""
import time
import uuid
from flask import Blueprint, request
from app.response import ok, fail
from app.storage.repos import (
    product_repo, address_repo, order_repo, user_coupon_repo,
)
from app.storage.order_ops import update_order
from app.current_user import current_user_id, current_user
from app.pricing import calc_amount, normalize_tiers, first_unit_price, substitute_zero_tiers
from app.coupons import (
    user_coupon_is_usable, applicable_to_amount, calc_discount,
)
# 复用 products 路由里的相对→绝对 URL 转换：DB 里 covers/cover_url 存的是
# /product/asset/... 这种相对路径，小程序 <image> 无法当网络图加载，必须补全为
# https://<host>/... 否则会被当成本地 bundle 资源静默失败。
from app.routes.products import _abs as _abs_url

bp = Blueprint("orders", __name__)

# 业务硬约束：用机最少 3 天（不含物流期）。商品后台不允许配置覆盖。
MIN_RENT_DAYS = 3

# 前端订单 Tab：key 与 order.status 一一对应
# 注：原本 audit→awaiting_face→send 三档；芝麻免押本身已含活体校验，
# 二次人脸冗余且拉低转化，故 awaiting_face 已废弃，免押成功直接进 send。
# return_inspecting = 用户已寄回、商家核验中（核验通过 → unfreeze → done）
ORDER_STATUS_TABS = [
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


_USER_STATUS_LABEL = {
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
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")

    # 上架校验：非 on（下架 off / 草稿 draft）一律不可下单，与库存无关
    # 列表只展示 on，但直连 product_id 调接口能绕过，这里硬堵
    if (p.get("status") or "") != "on":
        return fail(40023, "该商品已下架，无法下单")

    # 库存校验：库存 <= 0 禁止下单（后台把库存调 0 即等于下架不可租）
    if int(p.get("stock") or 0) <= 0:
        return fail(40022, "该商品库存不足，暂时无法下单")

    # 押金必填硬约束：避免历史数据漏配押金导致 deposit_freeze=0 让用户白嫖
    deposit_freeze = float(p.get("deposit_amount") or 0)
    if deposit_freeze <= 0:
        return fail(40020, "该商品押金未配置，请联系客服")

    uid = current_user_id()
    addr_id = body.get("address_id")
    addr = address_repo.get(addr_id) if addr_id else _default_address(uid)
    if not addr:
        return fail(40001, "请先添加收货地址")

    # 分段租金：用商品当前 price_tiers 计算实付，并把 tiers 快照存进订单，
    # 避免后续运营改价影响历史订单展示与对账。
    tiers = normalize_tiers(p.get("price_tiers") or [{"from": 1, "price": p.get("price") or 0}])
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
        amount = round(max(0.0, original_amount - discount), 2)
        coupon_snapshot.update({
            "coupon_id": int(used_uc.get("coupon_id") or 0),
            "user_coupon_id": used_uc["id"],
            "coupon_name": used_uc.get("name", ""),
            "coupon_threshold": float(used_uc.get("threshold") or 0),
            "coupon_discount": float(used_uc.get("discount") or 0),
            "discount_amount": discount,
        })

    # 冻结模式：跟随系统设置（freeze_includes_rent）
    #   True  → 押金 + 总租金（amount 是已扣优惠的实付租金）
    #   False → 仅押金
    # 落库为快照 freeze_amount，下单后改 setting 不影响本单
    from app import settings as app_settings
    includes_rent = bool(app_settings.get("freeze_includes_rent", True))
    freeze_amount = round(deposit_freeze + (amount if includes_rent else 0), 2)

    record = {
        "id": "O" + uuid.uuid4().hex[:12].upper(),
        "user_id": uid,
        "product_id": p["id"],
        "product_name": p["name"],
        "price_per_day": first_unit_price(tiers),
        "days": days,
        "amount": amount,
        "original_amount": original_amount,
        "price_tiers": tiers,
        "start_date": start_date,
        "end_date": end_date,
        "ship_days": ship_days,
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
      audit          → 直接 cancelled（无冻结物，秒退；同步回退优惠券）
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

    if status == "audit":
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


def transition_freeze_done(out_order_no: str) -> dict | None:
    """免押成功后 audit → send（跳过原来的 awaiting_face 人脸环节）。
    同时落 send_at = 当前 unix 秒，作为 48h 发货倒计时基准。
    """
    oid = order_id_from_out_order_no(out_order_no)
    o = order_repo.get(oid)
    if not o or o.get("status") != "audit":
        return o
    # 免押成功 = 设备正式被占用，此刻扣 1 库存（原子条件扣减，扣到 0 为止不扣成负）。
    # 放在这个 transition 里而非下单时：① 只有真正免押成功的单才占库存，未完成免押的
    # 不挤占；② 本函数已用 status==audit 做了幂等闸，支付宝重发 freeze 通知不会重复扣。
    # 归还/取消不在此自动加回，由后台人工调整库存（按业务约定）。
    pid = o.get("product_id")
    if pid:
        left = product_repo.try_decrement(pid, "stock", by=1, floor=0)
        if left is None:
            import logging
            logging.getLogger(__name__).warning(
                "freeze_done: 订单 %s 商品 %s 免押成功但库存已为 0，未扣减（请后台核对）",
                oid, pid,
            )
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
    """普通交易支付成功（补差价 / 续租）。当前仅查找日志占位，不强改主状态机。"""
    return order_repo.get(out_trade_no)


def transition_trade_refunded(out_trade_no: str) -> dict | None:
    """退款成功。当前仅查找日志占位。"""
    return order_repo.get(out_trade_no)
