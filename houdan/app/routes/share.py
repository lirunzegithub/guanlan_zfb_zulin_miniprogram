"""商品分享：获取分享卡片信息 + 行为上报。

接口契约：
  GET  /api/share/products/<pid>        → 分享卡片 payload（小程序 onShareAppMessage 直接用）
  POST /api/share/products/<pid>        body: {channel?}  → 上报一次分享行为
  GET  /api/share/stats/<pid>           → 单商品分享次数（debug/运营用）

分享卡片字段约定（与支付宝小程序 onShareAppMessage 对齐）：
  title       分享标题
  desc        分享描述
  image_url   分享缩略图（绝对 URL）
  path        小程序内的目标页面（带 query）
  h5_url      落地页 H5（可选，用于复制链接 / 浏览器打开）
"""
from __future__ import annotations

from flask import Blueprint, request

from app.response import ok, fail
from app.config import AlipayConfig
from app.storage.repos import product_repo, share_log_repo
from app.current_user import current_user_id

bp = Blueprint("share", __name__)

_ALLOWED_CHANNELS = {"alipay", "link", "poster", "qrcode", "other"}
_SHARE_PATH_TMPL = "/pages/product/product?id={pid}"


def _abs_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return AlipayConfig.NOTIFY_BASE.rstrip("/") + url
    return url


def _first_cover(p: dict) -> str:
    covers = p.get("covers") or []
    if isinstance(covers, list) and covers:
        return _abs_url(covers[0])
    return _abs_url(p.get("cover_url") or "")


def _share_payload(p: dict) -> dict:
    pid = p["id"]
    name = (p.get("name") or "").strip() or "好物推荐"
    min_price = p.get("min_price") or 0
    desc_parts = [f"¥{min_price}/天起"]
    tip = (p.get("tip") or "").strip()
    if tip:
        desc_parts.append(tip)
    return {
        "product_id": pid,
        "title": name,
        "desc": " · ".join(desc_parts),
        "image_url": _first_cover(p),
        "path": _SHARE_PATH_TMPL.format(pid=pid),
        "h5_url": _abs_url(f"/product?id={pid}"),
    }


@bp.get("/products/<int:pid>")
def get_share_info(pid: int):
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")
    return ok(_share_payload(p))


@bp.get("/products/<int:pid>/qrcode")
def share_qrcode(pid: int):
    """海报用：返回指向该商品详情页的小程序码图片 URL（带缓存）。

    小程序码生成走 alipay.open.app.qrcode.create，成本较高且有频控，
    因此把结果缓存进商品记录的 share_qr_url 字段，后续命中缓存直接返回。

    优雅降级：小程序未上线 / alipay client 未配置 / 接口异常时，统一返回
    空串而非报错——前端海报"无码"也能正常出图，不阻断分享主流程。
    """
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")

    # 与后台共用同一份缓存（product.qr_cache，按租期天数为 key；"0" = 默认无租期），
    # 默认码只生成一次，后台/小程序都命中缓存，避免支付宝频控导致"忽好忽坏"。
    cache = p.get("qr_cache")
    cache = cache if isinstance(cache, dict) else {}
    cached = (cache.get("0") or "").strip()
    if cached:
        return ok({"qr_code_url": cached})

    page = "pages/product/product"
    query = f"id={pid}"
    url_param = f"{page}?{query}"   # query 内联，扫码后 onLoad 直接拿到 q.id
    describe = ((p.get("name") or "商品").strip() + " 分享")[:30]

    try:
        from app.alipay_client import get_client
        qr_url = (get_client().create_app_qrcode(
            url_param=url_param,
            query_param=query,
            describe=describe,
        ) or "").strip()
    except Exception:
        return ok({"qr_code_url": ""})

    if not qr_url:
        return ok({"qr_code_url": ""})

    try:
        new_cache = dict(cache)
        new_cache["0"] = qr_url
        product_repo.update(pid, {"qr_cache": new_cache})
    except Exception:
        pass
    return ok({"qr_code_url": qr_url})


@bp.post("/products/<int:pid>")
def log_share(pid: int):
    if not product_repo.get(pid):
        return fail(404, "商品不存在")
    body = request.get_json(silent=True) or {}
    channel = (body.get("channel") or "alipay").strip().lower()
    if channel not in _ALLOWED_CHANNELS:
        channel = "other"
    rec = share_log_repo.create({
        "user_id": current_user_id(),
        "product_id": pid,
        "channel": channel,
        "ua": (request.headers.get("User-Agent") or "")[:200],
    })
    return ok({"id": rec["id"], "channel": channel}, "分享已记录")


@bp.get("/stats/<int:pid>")
def share_stats(pid: int):
    logs = share_log_repo.list(product_id=pid)
    by_channel: dict[str, int] = {}
    for r in logs:
        c = r.get("channel") or "other"
        by_channel[c] = by_channel.get(c, 0) + 1
    return ok({
        "product_id": pid,
        "total": len(logs),
        "by_channel": by_channel,
    })
