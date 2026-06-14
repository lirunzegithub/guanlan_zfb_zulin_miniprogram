"""把内部订单状态同步到支付宝订单中心（alipay.merchant.order.sync · 类目 3C_RENT）。

设计原则：
- 失败不抛错 —— 不能因为支付宝端网络/接口校验失败导致主业务回滚
- 一律落 notify_log（channel="merchant_order_sync"），运营/排查可在通知日志页筛查
- 同步元数据写回订单本身（sync_ok / sync_at / sync_err / sync_status），便于"重试同步"

协议要点（详见 docs/ORDER_CENTER_SYNC.md）：
- merchant_biz_type = "3C_RENT"
- 状态/类目/详情链接/business_info 都塞 ext_info 数组
- item_order_list 必填，每个 item 需要 image_material_id（先用空串占位）
"""
from __future__ import annotations

import logging
import time

from app.alipay_client import get_client
from app.config import AlipayConfig
from app.notify_log import record as notify_record
from app.storage.repos import order_repo, product_repo

logger = logging.getLogger(__name__)


# 内部 status → alipay 3C_RENT merchant_order_status
# 完整状态枚举详见 docs/ORDER_CENTER_SYNC.md §2.1
_STATUS_MAP: dict[str, str | None] = {
    "audit":             "DEPOSIT_WAIVER",  # 待免押
    "send":              "TO_SEND_GOODS",   # 待发货
    # pending_cancel 是内部审核中间态：支付宝那边订单实际还在 TO_SEND_GOODS。
    # 强行推 PENDING 会被支付宝判"订单状态乱序"（INVALID_PARAMETER），
    # 因为 PENDING 在支付宝是"刚创建待商家确认"的前置态，不能从已确认的
    # TO_SEND_GOODS 倒回。商家审核结果出来后（驳回→send/同意→cancelled）
    # 再走正常 sync，等价于支付宝那边一直保持 TO_SEND_GOODS 直到终态。
    "pending_cancel":    None,
    "recv":              "IN_DELIVERY",     # 已发货（用户视角等签收）
    "using":             "IN_THE_LEASE",    # 租赁中
    "return":            "RENT_DUE",        # 租赁到期（等用户归还）
    "overdue":           "OVERDUE",         # 已逾期
    "return_inspecting": "IN_THE_BACK",     # 归还中（用户已寄回，商家核验/扣款中）
    "done":              "FINISHED",        # 已归还
    "cancelled":         "CLOSED",          # 已关闭
}


def _fmt_time(ts: int | None) -> str:
    """unix 秒 → 'yyyy-MM-dd HH:mm:ss'。None/0 返回空串。"""
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(ts)))


def _fmt_time_ms(ts: float | None = None) -> str:
    """当前时间 → 'yyyy-MM-dd HH:mm:ss.SSS'（毫秒精度，order_modified_time 用）"""
    t = ts if ts is not None else time.time()
    base = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
    return f"{base}.{int((t - int(t)) * 1000):03d}"


def _receiving_ts(order: dict) -> int:
    """估算「收货时间」unix 秒，给 business_info.receiving_time 用。

    优先级：
      lease_started_at  —— recv→using 的真实时间戳（最准）
      shipped_at + ship_days*86400  —— 物流期结束 = 默认开始用机
      0  —— 既没发货也没开始租，留空
    """
    started = int(order.get("lease_started_at") or 0)
    if started:
        return started
    shipped = int(order.get("shipped_at") or 0)
    if shipped:
        days = int(order.get("ship_days") or 0) or 3
        return shipped + days * 86400
    return 0


def _build_business_info(order: dict) -> dict:
    """拼 business_info JSON（按 3C_RENT 类目字段约定）。
    类型一律 String；没值的字段不传（除非该状态强制必填，那时也传空串占位）。
    """
    days = int(order.get("days") or 0)
    amount = float(order.get("amount") or 0)
    info = {
        "total_rent":     f"{amount:.2f}",
        "lease":          f"{days}天" if days else "",
        "cash_pledge":    f"{float(order.get('deposit_freeze') or 0):.2f}",
        "thaw_deposit":   f"{float(order.get('deposit_freeze') or 0):.2f}",
        # SERVICE_MSG 分发场景文档推荐字段；不传会导致订单消息分发失败
        "first_rent":     f"{amount:.2f}",
        "payment_amount": f"{amount:.2f}",
    }
    if order.get("shipped_at"):
        info["delivery_time"] = _fmt_time(order["shipped_at"])
    # 收货时间：SERVICE_MSG（订单消息）场景必填——之前没拼这个字段，
    # 阿里 distribute_result 会返回 "缺少必填属性 ext_info.business_info.receiving_time"。
    ts = _receiving_ts(order)
    if ts:
        info["receiving_time"] = _fmt_time(ts)
    if order.get("logistics_no"):
        info["courier_number"] = order["logistics_no"]
    if order.get("end_date"):
        info["rent_due_date"] = order["end_date"]
        info["give_back_date"] = order["end_date"]
    if order.get("start_date") and order.get("end_date"):
        info["lease_period"] = f"{order['start_date']}--{order['end_date']}"
    if order.get("coupon_name"):
        info["discount_name"] = order["coupon_name"]
    return info


def _product_info(pid) -> tuple[str, str]:
    """返回 (商品名, image_material_id)。material_id 没上传过则空串占位。"""
    if not pid:
        return "租赁商品", ""
    p = product_repo.get(pid) or {}
    name = p.get("name") or "租赁商品"
    material_id = (p.get("alipay_image_material_id") or "").strip()
    return name, material_id


def sync_order(oid: str, *, reason: str = "") -> tuple[bool, str]:
    """把订单当前状态同步到支付宝订单中心。
    成功：(True, "")；失败：(False, err_msg)。一律落 notify_log + 写回订单 sync_*。
    """
    order = order_repo.get(oid)
    if not order:
        return False, "订单不存在"

    internal = order.get("status") or ""
    # _STATUS_MAP 中显式声明为 None 的状态 = 内部中间态，不推到支付宝（如 pending_cancel）。
    # 跟"未知状态"区分开：未知状态算错误回退，None 算合法跳过。
    if internal in _STATUS_MAP and _STATUS_MAP[internal] is None:
        # 不动 sync_* 元数据（保留上一次成功的 sync_status，便于运营看历史），
        # 只在 notify_log 里记一条"已跳过"供排查
        notify_record(
            channel="merchant_order_sync",
            params={"oid": oid, "internal": internal, "reason": reason or "", "skipped": True},
            verified=True, business_ok=True,
            note=f"skipped: {internal} 为内部中间态 ({reason or 'manual'})",
        )
        return True, ""
    alipay_status = _STATUS_MAP.get(internal)
    if not alipay_status:
        return False, f"无法映射内部状态 '{internal}'"

    buyer_id = (order.get("user_id") or "").strip()
    if not buyer_id:
        return False, "订单缺少 user_id（支付宝 buyer_id）"

    product_name, material_id = _product_info(order.get("product_id"))
    business_info = _build_business_info(order)
    link_page = f"/pages/order-detail/order-detail?id={oid}"

    err_msg = ""
    api_ok = False        # 顶层 API 调用是否返回 code=10000
    distribute_warnings: list[str] = []
    resp: dict = {}
    try:
        resp = get_client().merchant_order_sync(
            out_biz_no=oid,
            buyer_id=buyer_id,
            merchant_order_status=alipay_status,
            order_create_time=_fmt_time(order.get("created_at")) or _fmt_time(int(time.time())),
            order_modified_time=_fmt_time_ms(),
            amount=float(order.get("amount") or 0),
            pay_amount=float(order.get("amount") or 0),
            product_name=product_name,
            product_image_material_id=material_id,
            item_quantity="1",
            item_unit_price=float(order.get("amount") or 0),
            business_info=business_info,
            link_page=link_page,
            notify_url=AlipayConfig.NOTIFY_URL_MERCHANT_ORDER_SYNC,
        )
        api_ok = True
    except Exception as e:
        err_msg = str(e)
        logger.warning("merchant_order_sync failed oid=%s: %s", oid, err_msg)

    # 分发结果检查：响应体里 distribute_result 任一场景带 not_distribute_reason
    # 说明该场景（例如 SERVICE_MSG 订单消息）虽然主接口收下了，但派发失败，
    # 不应该当作完全 OK，得把告警暴露给运营。
    if api_ok and isinstance(resp.get("distribute_result"), list):
        for d in resp["distribute_result"]:
            reason_text = (d.get("not_distribute_reason") or "").strip()
            if not reason_text:
                continue
            scene = d.get("scene_name") or d.get("scene_code") or "未知场景"
            distribute_warnings.append(f"{scene}: {reason_text}")

    partial = bool(distribute_warnings)
    if partial:
        err_msg = "分发部分失败 - " + " / ".join(distribute_warnings)
        logger.warning("merchant_order_sync partial-fail oid=%s: %s", oid, err_msg)

    # 最终业务态：API 通过且无分发告警才算完全成功
    business_ok = api_ok and not partial

    # 写订单 sync_* 字段（运营在后台一眼看到同步状态）。
    # 即使分发告警，sync_status 依然写入（阿里订单中心已经更新），
    # 但 sync_ok=False 让前端「重试同步」按钮可点。
    order_repo.update(oid, {
        "sync_status": alipay_status if api_ok else order.get("sync_status") or "",
        "sync_ok":     business_ok,
        "sync_at":     int(time.time()),
        "sync_err":    "" if business_ok else err_msg[:500],
    })

    if not api_ok:
        note_tail = f" - {err_msg[:160]}"
    elif partial:
        note_tail = f" - WARN {err_msg[:160]}"
    else:
        note_tail = ""

    notify_record(
        channel="merchant_order_sync",
        params={
            "oid":            oid,
            "alipay_status":  alipay_status,
            "internal":       internal,
            "reason":         reason or "",
            "buyer_id":       buyer_id,
            "material_id":    material_id,
            "resp":           resp if api_ok else None,
            "err":            err_msg if not business_ok else "",
            "distribute_warnings": distribute_warnings,
        },
        verified=api_ok,            # 验签 / 顶层接口校验：与之前语义一致
        business_ok=business_ok,    # 业务层：分发告警时降级为 False
        note=f"{alipay_status} ({reason or 'manual'}){note_tail}",
    )

    # 给调用方的返回值用 business_ok 语义，这样外层 admin "重试同步"
    # 会真的报错出来，运营不会被绿色 toast 蒙住。
    return business_ok, err_msg


def sync_shipped(oid: str) -> tuple[bool, str]:
    """发货流程专用入口：调用方应保证订单已写入 logistics_* 和 status=recv。"""
    return sync_order(oid, reason="shipped")
