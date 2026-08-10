"""订单物流轨迹：小程序订单详情 / 后台订单详情共用的取数与缓存层。

【为什么要缓存】
顺丰路由查询是按次调用的外部接口，而订单详情页是用户最常刷的页面之一。
不缓存的话，用户在详情页来回切几次就是几十次外部调用，既拖慢页面
（每次都要等顺丰 RTT），也白白消耗配额。所以：轨迹存在订单里，
页面读缓存，过期了才回源。

【TTL 分两档】
    在途   30 分钟 —— 与 scheduler 的顺丰扫描同频，页面看到的不会比后台调度更旧
    已签收 24 小时 —— 签收后轨迹基本终结，再高频查纯属浪费
用户可以手动下拉刷新（force=True）绕过缓存，但那是用户主动触发的，频次可控。

【与 scheduler 的关系】
scheduler 只扫 status=recv 的单，签收后就不管了；而用户在「租赁中」
甚至「已完成」时依然会回来看物流。所以取数逻辑独立在这里，
两边都通过 sf_client 打同一个接口，互不依赖。
"""
from __future__ import annotations

import logging
import time

from app import sf_client
from app.storage.repos import order_repo

logger = logging.getLogger(__name__)

# 缓存有效期（秒）
TTL_IN_TRANSIT = 30 * 60
TTL_SIGNED = 24 * 3600

# 顺丰标准状态码 → 给用户看的中文。轨迹里 firstStatusName 本身就是中文，
# 这张表只用于兜底（个别响应不带 Name 字段）和前端做图标映射。
_FIRST_STATUS_LABEL = {
    "1": "已揽收",
    "2": "运送中",
    "3": "派送中",
    "4": "已签收",
}


def supported(order: dict) -> bool:
    """这个订单能不能查轨迹：顺丰单 + 有运单号 + 系统已配顺丰凭据。

    非顺丰单（京东等）不是错误，只是我们没有它们的接口，页面照常显示
    运单号，只是没有轨迹可展开。
    """
    if not order:
        return False
    return bool(
        sf_client.is_configured()
        and (order.get("logistics_company") or "").upper() == "SF"
        and (order.get("logistics_no") or "").strip()
    )


def _normalize(routes: list) -> list[dict]:
    """顺丰原始轨迹 → 前端直接可渲染的结构，按时间倒序（最新在最上，同淘宝京东）。

    只保留展示需要的字段。opCode 这类内部编码不下发给 C 端，
    但保留 first（标准状态码）供前端选图标/配色。
    """
    out = []
    for r in routes or []:
        if not isinstance(r, dict):
            continue
        first = str(r.get("firstStatusCode") or "").strip()
        out.append({
            "time":   (r.get("acceptTime") or "").strip(),
            "status": (r.get("secondaryStatusName") or r.get("firstStatusName")
                       or _FIRST_STATUS_LABEL.get(first, "")),
            "first":  first,
            "place":  (r.get("acceptAddress") or "").strip(),
            "desc":   (r.get("remark") or "").strip(),
            "signed": sf_client._is_signed_route(r),
        })
    # 顺丰返回是按时间正序的；倒序展示更符合用户习惯（最新进展在最上面）
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


def fetch(order: dict, *, force: bool = False) -> dict:
    """取订单的物流轨迹。命中缓存则不打外部接口。

    Args:
        order: 订单 dict
        force: True = 忽略缓存强制回源（用户手动刷新时用）

    Returns:
        {
          supported:  bool   该单是否支持查轨迹
          routes:     list   轨迹（倒序）
          synced_at:  int    这批轨迹的抓取时间
          cached:     bool   本次是否直接用的缓存
          signed_at:  str    签收时间（有则填），前端可直接展示
          error:      str    取数失败原因；有缓存时仍会照常返回 routes
          company:    str    快递公司中文名
          waybill_no: str
        }
    """
    from app import logistics as courier_meta

    lc = (order.get("logistics_company") or "").upper()
    courier = courier_meta.get(lc)
    base = {
        "supported":  supported(order),
        "routes":     order.get("logistics_routes") or [],
        "synced_at":  int(order.get("logistics_synced_at") or 0),
        "cached":     True,
        "signed_at":  "",
        "error":      "",
        "company":    courier.name if courier else lc,
        "waybill_no": (order.get("logistics_no") or "").strip(),
    }
    if not base["supported"]:
        return base

    now = int(time.time())
    # 已签收的单用长 TTL：轨迹已经终结，没必要每半小时再问一遍
    has_signed = any(r.get("signed") for r in base["routes"])
    ttl = TTL_SIGNED if has_signed else TTL_IN_TRANSIT
    if not force and base["routes"] and now - base["synced_at"] < ttl:
        base["signed_at"] = _signed_time(base["routes"])
        return base

    phone = ((order.get("address_snapshot") or {}).get("receiver_phone") or "")
    ok, data, code, raw_routes = sf_client.route_query_for_order(base["waybill_no"], phone)
    if not ok:
        # 取数失败不清空缓存：宁可给用户看半小时前的轨迹，也好过整块消失
        base["error"] = str(data)
        base["signed_at"] = _signed_time(base["routes"])
        logger.info("order_logistics fetch failed oid=%s: %s", order.get("id"), data)
        return base

    routes = _normalize(raw_routes)
    order_repo.update(order["id"], {
        "logistics_routes":    routes,
        "logistics_synced_at": now,
    })
    base.update({"routes": routes, "synced_at": now, "cached": False,
                 "signed_at": _signed_time(routes)})
    return base


def _signed_time(routes: list) -> str:
    """轨迹里的签收时间字符串；没签收返回空串。"""
    for r in routes or []:
        if r.get("signed"):
            return r.get("time") or ""
    return ""
