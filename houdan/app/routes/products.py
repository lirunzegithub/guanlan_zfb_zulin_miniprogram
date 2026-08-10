"""商品相关接口（走 product_repo）"""
import time

from flask import Blueprint, request, g, has_request_context
from app.response import ok, fail
from app.config import AlipayConfig
from app.storage.repos import product_repo, sku_repo, comment_repo, favorite_repo
from app.pricing import (
    normalize_tiers, derive_price_curve, min_unit_price, substitute_zero_tiers,
)


def _optional_user_id() -> str | None:
    """匿名浏览也允许：拿不到登录态就返回 None，按用户的字段降级即可。"""
    if not has_request_context():
        return None
    return getattr(g, "user_id", None)

bp = Blueprint("products", __name__)

# 详情页内嵌的评论条数；超过这条数前端走 /api/comments 拉更多
_DETAIL_COMMENTS_LIMIT = 2


# 列表卡片所需字段（详情字段在 detail 接口里给）
# 押金 deposit_amount 故意不在列表卡里暴露：列表只露出价格与销量，进入详情页才看押金。
_LIST_FIELDS = (
    "id", "cat_id", "name", "min_price", "sales",
    "cover_url", "covers",
)


def _abs(url: str) -> str:
    """把相对路径（以 / 开头）补齐为公网绝对 URL，让小程序能跨域加载。"""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return AlipayConfig.notify_base() + url
    return url


def _covers_of(p: dict) -> list[str]:
    """归一化封面：优先用 covers 数组；为空时退化到旧字段 cover_url 单值。
    输出全部为绝对 URL，已剔除空串。
    """
    raw = p.get("covers")
    if not isinstance(raw, list) or not raw:
        raw = [p.get("cover_url") or ""]
    return [u for u in (_abs(x) for x in raw) if u]


def _bg_of(p: dict) -> str:
    """首张封面包装为 background shorthand；无封面时为空串（前端 CSS 提供占位）。"""
    covers = _covers_of(p)
    return f'url("{covers[0]}") center/cover no-repeat' if covers else ""


def _protect_tiers(tiers: list) -> list:
    """零价兜底（"保险"逻辑）：保护开启时把 0 元日租金档替换成 min_price_floor（默认 20）。
      allow_zero_rent=False（正常租赁）→ 启用：0 → 兜底值，作用于起价/明细/计费全程
      allow_zero_rent=True （租押分离）→ 关闭：0 照实保留
    实时读 settings，后台切开关立刻生效。
    """
    from app.settings import get as _setting_get
    if bool(_setting_get("allow_zero_rent", False)):
        return tiers
    try:
        fallback = float(_setting_get("min_price_floor", 20) or 0)
    except (TypeError, ValueError):
        fallback = 20.0
    return substitute_zero_tiers(tiers, fallback)


def _on_sale_skus(pid) -> list[dict]:
    """该商品在售的 SKU（status=on），按 sort / id 排序（repo.list 已保证）。
    正常商品恒有至少一个；返回空列表只可能是 SKU 全被下架了。
    """
    return [s for s in sku_repo.list(product_id=pid) if (s.get("status") or "on") == "on"]


def _sales_of(pid, fallback=0) -> int:
    """SKU 存在时汇总全部 SKU 的历史销量（包括已下架 SKU）。"""
    skus = sku_repo.list(product_id=pid)
    if skus:
        return sum(int(s.get("sales") or 0) for s in skus)
    return int(fallback or 0)


def _sku_card(s: dict, product_covers: list[str]) -> dict:
    """SKU 的对外视图：只给小程序渲染和算价需要的字段，租金按 tiers 实时重算。
    没配独立封面的 SKU 回落商品首图，保证前端切换 SKU 时图不会闪空。
    """
    tiers = _protect_tiers(normalize_tiers(s.get("price_tiers") or []))
    cover = _abs((s.get("cover_url") or "").strip())
    return {
        "id":             s.get("id"),
        "name":           s.get("name") or "",
        "cover_url":      cover or (product_covers[0] if product_covers else ""),
        "price_tiers":    tiers,
        "min_price":      min_unit_price(tiers),
        "price_curve":    derive_price_curve(tiers),
        "deposit_amount": float(s.get("deposit_amount") or 0),
        "stock":          int(s.get("stock") or 0),
    }


def _to_card(p: dict) -> dict:
    card = {k: p.get(k) for k in _LIST_FIELDS}
    covers = _covers_of(p)
    card["covers"] = covers
    card["cover_url"] = covers[0] if covers else ""
    card["bg"] = _bg_of(p)
    card["sales"] = _sales_of(p.get("id"), p.get("sales"))
    card.pop("cover_bg", None)
    # min_price 按 price_tiers 实时算（与详情口径一致）+ 零价兜底，不用存库旧值。
    raw_tiers = p.get("price_tiers")
    if isinstance(raw_tiers, list) and raw_tiers:
        card["min_price"] = min_unit_price(_protect_tiers(normalize_tiers(raw_tiers)))
    else:
        card["min_price"] = p.get("min_price")   # 无 tiers 的极端老数据才退回存库值

    # 列表卡起价 = 所有在售 SKU 里最低的那个（"¥X 起"要名副其实）
    skus = _on_sale_skus(p.get("id"))
    if skus:
        prices = [
            min_unit_price(_protect_tiers(normalize_tiers(s.get("price_tiers") or [])))
            for s in skus
        ]
        prices = [x for x in prices if x is not None]
        if prices:
            card["min_price"] = min(prices)
    card["sku_count"] = len(skus)
    return card


@bp.get("")
def list_products():
    cat_id  = request.args.get("cat_id", type=int)
    keyword = (request.args.get("keyword") or "").strip()
    page    = max(request.args.get("page", default=1, type=int), 1)
    size    = min(request.args.get("size", default=20, type=int), 100)

    filters = {"status": "on"}
    if cat_id:
        filters["cat_id"] = cat_id
    if keyword:
        filters["name__contains"] = keyword

    items = product_repo.list(**filters)
    total = len(items)
    start = (page - 1) * size
    return ok({
        "list": [_to_card(p) for p in items[start:start + size]],
        "total": total,
        "page": page,
        "size": size,
    })


@bp.get("/<int:pid>")
def detail(pid):
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")
    # 详情页 hero 优先用 p.covers 多图轮播，p.bg 用首张做 fallback。
    # 旧数据只有 cover_url 时 _covers_of 会自动补一项。
    covers = _covers_of(p)
    p["covers"] = covers
    p["cover_url"] = covers[0] if covers else ""
    p["bg"] = _bg_of(p)
    p.pop("cover_bg", None)        # cover_bg 已废弃，前端 CSS 提供占位
    p.pop("subtitle", None)        # subtitle 已废弃
    p.pop("tip", None)             # tip 已废弃
    if isinstance(p.get("real_shots"), list):
        p["real_shots"] = [_shot_url(s) for s in p["real_shots"]]

    # 分段租金：以 price_tiers 为唯一数据源；min_price / price_curve 是派生字段，
    # 详情接口每次重算一遍，避免库里旧值漂移。
    # 零价兜底作用在 tiers 层 → 起价/明细/折线/小程序算租金 全程一致
    tiers = _protect_tiers(normalize_tiers(p.get("price_tiers") or []))
    p["price_tiers"] = tiers
    p["min_price"] = min_unit_price(tiers)
    p["price_curve"] = derive_price_curve(tiers)

    # SKU：价格/押金/库存的真相都在这里。商品级同名字段用 SKU 汇总值覆盖，
    # 这样"已租罄""¥X 起"这类既有判断不用改也正确。
    p["sku_option_name"] = (p.get("sku_option_name") or "SKU").strip() or "SKU"
    sku_cards = [_sku_card(s, covers) for s in _on_sale_skus(pid)]
    p["skus"] = sku_cards
    p["sales"] = _sales_of(pid, p.get("sales"))
    if sku_cards:
        p["stock"] = sum(s["stock"] for s in sku_cards)
        p["min_price"] = min(s["min_price"] for s in sku_cards)
    p.pop("price", None)
    p.pop("promo_label", None)
    p.pop("activity", None)
    p.pop("discounts", None)       # 已废弃的"满 N 天 X 折"标签

    # 权益条统一规整：① 剔除合规违规的"芝麻信用免押金"
    #                  ② 补齐"实时电话客服"，所有商品共用同一组权益，避免逐个改 DB
    raw_rights = p.get("rights") if isinstance(p.get("rights"), list) else []
    rights = [
        r for r in raw_rights
        if (r or {}).get("key") != "credit"
        and "芝麻" not in str((r or {}).get("label") or "")
    ]
    if not any((r or {}).get("key") == "tel" for r in rights):
        rights.append({"key": "tel", "label": "实时电话客服", "icon": "tel"})
    else:
        # 历史 DB 里存的是"18 小时电话客服"，统一改口径，免得逐条改数据
        for r in rights:
            if (r or {}).get("key") == "tel":
                r["label"] = "实时电话客服"
    p["rights"] = rights

    # 评论从独立 comments 表查最新若干条嵌进来，保留旧的 p.comments 字段形态
    all_comments = comment_repo.list(product_id=pid)
    all_comments.sort(key=lambda x: -int(x.get("created_at") or 0))
    p["comments_total"] = len(all_comments)
    p["comments"] = [_comment_view(c) for c in all_comments[:_DETAIL_COMMENTS_LIMIT]]

    # 收藏状态：当前用户视角的 favorited（前端首屏直接渲染爱心，避免再发一次请求）
    # 详情页是公开页，未登录用户也能浏览 → 没有 uid 时 favorited 恒为 false
    uid = _optional_user_id()
    p["favorited"] = bool(favorite_repo.find(user_id=uid, product_id=pid)) if uid else False
    return ok(p)


def _comment_view(c: dict) -> dict:
    """与 routes/comments.py 输出形态一致：补 time 字段 + images 绝对化。"""
    ts = int(c.get("created_at") or 0)
    out = dict(c)
    out["time"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
    )
    raw_imgs = c.get("images") if isinstance(c.get("images"), list) else []
    out["images"] = [u for u in (_abs(x) for x in raw_imgs) if u]
    return out


def _shot_url(s: str) -> str:
    """real_shots 输出原始 URL：URL/相对路径 → 拼绝对；其他（旧渐变占位）原样保留。
    前端用 <image> 标签渲染，会按 URL 形态过滤；非 URL 项自动被丢弃。
    """
    s = (s or "").strip()
    if s.startswith(("http://", "https://", "data:", "/")):
        return _abs(s)
    return s
