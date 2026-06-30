"""管理后台 API（统一前缀 /api/admin）

接口契约：
  GET    /api/admin/stats
  GET    /api/admin/banners
  POST   /api/admin/banners
  PUT    /api/admin/banners/<id>
  DELETE /api/admin/banners/<id>
  GET    /api/admin/categories  (POST/PUT/DELETE 同上)
  GET    /api/admin/products    (POST/PUT/DELETE 同上)
  GET    /api/admin/users
  PUT    /api/admin/users/<id>

鉴权暂未启用，仅留一个 _check_auth 占位钩子，未来接入 Token / Session 时
在此统一加 @auth_required。
"""
import os
import time
import uuid

from flask import Blueprint, request, g
from app.response import ok, fail
from app.storage.repos import (
    banner_repo, category_repo, product_repo, user_repo, staff_repo,
    comment_repo, coupon_repo, user_coupon_repo,
    order_repo, address_repo, trade_repo, faq_repo, order_note_repo,
)
from app.storage.order_ops import update_order
from app.notify_log import list_recent as list_notify_logs, clear as clear_notify_logs
from app import auth_token
from app import logistics
from app.auth_password import hash_password, verify_password
from app.config import AlipayConfig
from app.pricing import (
    validate_tiers, normalize_tiers,
    min_unit_price, derive_price_curve,
)

bp = Blueprint("admin", __name__)


# 这些路径无需登录即可访问
_PUBLIC_PATHS = {
    "/api/admin/auth/login",
}


def _safe_staff(s: dict) -> dict:
    """去掉密码哈希再返回前端。"""
    return {k: v for k, v in s.items() if k != "password_hash"}


@bp.before_request
def _guard():
    if request.path in _PUBLIC_PATHS:
        return
    token = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    sess = auth_token.get(token)
    if not sess:
        return fail(401, "请登录")
    staff = staff_repo.get(sess["staff_id"])
    if not staff:
        auth_token.revoke(token)
        return fail(401, "账号不存在")
    g.staff = staff
    g.token = token


# ============ 登录 / 我 / 登出 ============

@bp.post("/auth/login")
def auth_login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return fail(1, "请输入用户名和密码")

    s = staff_repo.find(username=username)
    if not s:
        return fail(1, "用户名或密码错误")
    if not verify_password(password, s.get("password_hash", "")):
        return fail(1, "用户名或密码错误")

    staff_repo.update(s["id"], {"last_login_at": int(time.time())})
    token = auth_token.login(s["id"])
    return ok({
        "token": token,
        "staff": _safe_staff(staff_repo.get(s["id"])),
    }, "登录成功")


@bp.get("/auth/me")
def auth_me():
    return ok(_safe_staff(g.staff))


@bp.post("/auth/logout")
def auth_logout():
    auth_token.revoke(g.token)
    return ok(None, "已登出")


# ---------- Dashboard 统计 ----------
@bp.get("/stats")
def stats():
    products = product_repo.list()
    on_sale = [p for p in products if p.get("status") == "on"]
    cats = category_repo.list()
    banners = banner_repo.list()
    orders = order_repo.list()
    total_stock = sum(int(p.get("stock") or 0) for p in products)
    total_sales = sum(int(p.get("sales") or 0) for p in products)

    order_status_count: dict[str, int] = {}
    revenue_paid = 0.0  # 已收租金（订单进入 send 之后视为成交；取消单不计）
    for o in orders:
        st = o.get("status") or ""
        order_status_count[st] = order_status_count.get(st, 0) + 1
        if st in ("send", "recv", "using", "return", "overdue", "done"):
            revenue_paid += float(o.get("amount") or 0)

    in_progress = sum(
        order_status_count.get(s, 0)
        for s in ("audit", "send", "recv", "using", "return", "overdue")
    )

    return ok({
        "product_total": len(products),
        "product_on_sale": len(on_sale),
        "category_total": len(cats),
        "banner_total": len(banners),
        "user_total": len(user_repo.list()),
        "stock_total": total_stock,
        "sales_total": total_sales,
        "order_total": len(orders),
        "order_in_progress": in_progress,
        "order_status_count": order_status_count,
        "revenue_paid": round(revenue_paid, 2),
        "recent_products": [
            {"id": p["id"], "name": p["name"], "min_price": p.get("min_price"), "sales": p.get("sales")}
            for p in sorted(products, key=lambda x: x.get("updated_at", 0), reverse=True)[:5]
        ],
    })


# ---------- 字段白名单 ----------
# 系统字段永远不允许调用方写入；enabled 已废弃（删除=真删）
_SYSTEM_FIELDS = frozenset({"id", "created_at", "updated_at", "enabled"})

_ALLOWED = {
    "banners": frozenset({
        "position", "slot", "title", "subtitle",
        "tag", "tag_style", "image_url", "bg",
        "link_type", "link_value",
        "start_at", "end_at",
        "sort",
    }),
    "categories": frozenset({
        "name", "parent_id", "icon_url", "cover_url", "description",
        "service_id", "alipay_category",
        "sort",
    }),
    "products": frozenset({
        "cat_id", "name", "subtitle",
        "cover_url", "cover_bg", "covers",
        "min_price", "rent_unit", "deposit_amount",
        "max_rent_days", "stock", "sales", "rented_count",
        "service_id",
        "intro", "shipping", "shipping_note",
        "price_tiers",
        "price_curve", "rights", "real_shots", "spec_groups",
        "damage_standard",
        "shop",
        "status", "sort",
    }),
    "coupons": frozenset({
        "name", "threshold", "discount", "status",
        "start_at", "end_at",
        "total_quantity", "per_user_limit",
        "remark", "sort",
    }),
    "faqs": frozenset({
        "q", "a", "sort",
    }),
}


def _sanitize(prefix: str, body: dict) -> tuple[dict, list[str]]:
    """剔除系统字段 + 白名单过滤；返回 (干净 body, 被丢弃的字段名)。"""
    allowed = _ALLOWED.get(prefix, set())
    cleaned, dropped = {}, []
    for k, v in (body or {}).items():
        if k in _SYSTEM_FIELDS:
            dropped.append(k)
            continue
        if k not in allowed:
            dropped.append(k)
            continue
        cleaned[k] = v
    return cleaned, dropped


def _validate_product_deposit(body: dict, *, required: bool) -> str | None:
    """押金校验：新增必须带正数 deposit_amount；编辑时若提交了该字段则必须正数。
    返回错误消息（None 表示通过）。
    """
    if "deposit_amount" in body:
        try:
            v = float(body.get("deposit_amount") or 0)
        except (TypeError, ValueError):
            return "押金额度必须为数字"
        if v <= 0:
            return "押金额度必须大于 0"
    elif required:
        return "押金额度为必填项"
    return None


def _validate_product_pricing(body: dict, *, required: bool) -> str | None:
    """租金校验：新增必须带 price_tiers；每段日租金默认必须 > 0。

    系统设置 allow_zero_rent=True 时（租押分离场景）放宽为允许 0（仅拦负数），
    用于"租金另行/线下处理、仅冻押金担保"的商品。
    """
    from app.settings import get as _setting_get
    allow_zero = bool(_setting_get("allow_zero_rent", False))

    if "price_tiers" in body:
        tiers = body.get("price_tiers")
        if not isinstance(tiers, list) or not tiers:
            return "请配置至少一段日租金"
        for i, t in enumerate(tiers):
            try:
                p = float((t or {}).get("price") or 0)
            except (TypeError, ValueError):
                return f"第 {i+1} 段日租金必须为数字"
            if allow_zero:
                if p < 0:
                    return f"第 {i+1} 段日租金不能为负"
            elif p <= 0:
                return f"第 {i+1} 段日租金必须大于 0"
    elif required:
        return "请配置日租金（price_tiers）"
    return None


def _apply_pricing_derivations(body: dict) -> None:
    """商品分段租金的副产物：min_price = 最便宜段单价；price_curve = 由 tiers
    派生的采样折线点。在保存前同步刷一遍，确保展示字段与 tiers 永远一致，
    调用方传的相同字段会被覆盖。
    """
    tiers = body.get("price_tiers")
    if not isinstance(tiers, list) or not tiers:
        return
    body["price_tiers"] = normalize_tiers(tiers)
    body["min_price"] = min_unit_price(body["price_tiers"])
    body["price_curve"] = derive_price_curve(body["price_tiers"])


def _apply_damage_standard_normalize(body: dict) -> None:
    """定损标准：清洗 groups/rows 里的脏数据（空段过滤、字段补齐），保证前端可直接渲染。
    没提交该字段时不动；显式提交 {} / None 会保存为空 dict（前端按"未配置"处理）。
    """
    if "damage_standard" not in body:
        return
    ds = body.get("damage_standard")
    if not isinstance(ds, dict):
        body["damage_standard"] = {}
        return

    groups_in = ds.get("groups") if isinstance(ds.get("groups"), list) else []
    cleaned_groups = []
    for g in groups_in:
        if not isinstance(g, dict):
            continue
        gtype = (g.get("type") or "").strip()
        rows_in = g.get("rows") if isinstance(g.get("rows"), list) else []
        cleaned_rows = []
        for r in rows_in:
            if not isinstance(r, dict):
                continue
            row = {
                "degree": (r.get("degree") or "").strip(),
                "depreciation": (r.get("depreciation") or "").strip(),
                "insurance": (r.get("insurance") or "").strip(),
                "depreciation_highlight": bool(r.get("depreciation_highlight")),
                "insurance_highlight": bool(r.get("insurance_highlight")),
            }
            if row["degree"] or row["depreciation"] or row["insurance"]:
                cleaned_rows.append(row)
        if gtype or cleaned_rows:
            cleaned_groups.append({"type": gtype, "rows": cleaned_rows})

    headers = ds.get("headers") if isinstance(ds.get("headers"), dict) else {}
    body["damage_standard"] = {
        "enabled": bool(ds.get("enabled", True)),
        "title": (ds.get("title") or "定损标准").strip() or "定损标准",
        "headers": {
            "type": (headers.get("type") or "磨损类型").strip() or "磨损类型",
            "degree": (headers.get("degree") or "磨损程度").strip() or "磨损程度",
            "depreciation": (headers.get("depreciation") or "折旧标准").strip() or "折旧标准",
            "insurance": (headers.get("insurance") or "安心保标准").strip() or "安心保标准",
        },
        "groups": cleaned_groups,
        "notice": (ds.get("notice") or "").strip(),
    }


def _apply_product_covers_sync(body: dict) -> None:
    """封面图：覆盖 covers 时清洗为字符串数组，并把 cover_url 同步为 covers[0]。
    只在调用方提交 covers 字段时生效（避免误把 cover_url 单独编辑场景擦掉）。
    """
    if "covers" not in body:
        return
    raw = body.get("covers") or []
    if not isinstance(raw, list):
        raw = []
    cleaned = [s.strip() for s in raw if isinstance(s, str) and s.strip()]
    body["covers"] = cleaned
    body["cover_url"] = cleaned[0] if cleaned else ""


# 上传目录（与下方 /upload 端点共享）；模块顶部尚未声明，这里前向引用一下
def _local_path_for_cover(url: str) -> str | None:
    """把 /product/asset/products/uploads/... 形态的封面 URL 映射到磁盘文件路径。
    其他形态（外网 URL、绝对路径、空值）返回 None，调用方应跳过上传。
    """
    if not isinstance(url, str):
        return None
    s = url.strip()
    if not s.startswith("/product/asset/products/uploads/"):
        return None
    rel = s[len("/product/asset/products/uploads/"):]
    upload_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "static", "products", "uploads")
    )
    path = os.path.normpath(os.path.join(upload_root, rel))
    # 防越权：normpath 后必须仍在 upload_root 下
    if not path.startswith(upload_root):
        return None
    return path if os.path.exists(path) else None


def _sync_product_alipay_material(product_id) -> None:
    """商品保存后异步触发：covers[0] 若与 alipay_image_source 不同 → 上传到
    支付宝素材库，把返回的 image_id 写回 product.alipay_image_material_id。

    失败仅 log，不抛错；下次保存还会再试，永远不阻塞商品保存动作。

    所有分支（skip / cleared / uploaded / failed）都会落一条 notify_log，
    channel="alipay_material_upload"，运营在「回调日志」页能看到调用历史。
    """
    import logging
    from app.notify_log import record as notify_record

    logger = logging.getLogger(__name__)

    p = product_repo.get(product_id)
    if not p:
        return

    new_cover = ""
    if isinstance(p.get("covers"), list) and p["covers"]:
        new_cover = (p["covers"][0] or "").strip()
    if not new_cover:
        new_cover = (p.get("cover_url") or "").strip()

    # 「alipay_image_source」带版本前缀：升 API 后历史值自然失效，触发一次重传
    # v2 = 改用 alipay.merchant.item.file.upload（v1 错误地用了 offline.material.image.upload）
    source_signature = f"v2:{new_cover}" if new_cover else ""
    old_source = (p.get("alipay_image_source") or "").strip()
    old_material = (p.get("alipay_image_material_id") or "").strip()

    # 没换图（且签名一致）→ 跳过；只在还从未上传过时才记日志，避免噪音
    if source_signature == old_source:
        if not old_material:
            notify_record(
                channel="alipay_material_upload",
                params={
                    "product_id":  product_id,
                    "product_name": p.get("name") or "",
                    "outcome":     "skip_no_change",
                    "cover":       new_cover,
                },
                verified=True,
                business_ok=False,
                note=f"#{product_id} 主图未变更，跳过上传（material_id 仍为空）",
            )
        return

    # 主图被清空 → 把 material_id 一起清掉
    if not new_cover:
        product_repo.update(product_id, {
            "alipay_image_material_id": "",
            "alipay_image_source": "",
        })
        notify_record(
            channel="alipay_material_upload",
            params={
                "product_id":   product_id,
                "product_name": p.get("name") or "",
                "outcome":      "cleared",
                "previous":     old_source,
            },
            verified=True,
            business_ok=True,
            note=f"#{product_id} 主图已清空，material_id 已清",
        )
        return

    file_path = _local_path_for_cover(new_cover)
    if not file_path:
        logger.warning(
            "alipay material upload skipped: 无法定位本地文件 product_id=%s cover=%s",
            product_id, new_cover,
        )
        notify_record(
            channel="alipay_material_upload",
            params={
                "product_id":   product_id,
                "product_name": p.get("name") or "",
                "outcome":      "skip_remote_url",
                "cover":        new_cover,
            },
            verified=True,
            business_ok=False,
            note=f"#{product_id} 跳过：封面非本地路径（外链/缺失），无法读盘",
        )
        return

    try:
        from app.alipay_client import get_client
        material_id = get_client().upload_merchant_item_file(file_path)
    except Exception as e:
        err_msg = str(e)
        logger.warning("alipay material upload failed product_id=%s err=%s", product_id, err_msg)
        notify_record(
            channel="alipay_material_upload",
            params={
                "product_id":   product_id,
                "product_name": p.get("name") or "",
                "outcome":      "failed",
                "cover":        new_cover,
                "err":          err_msg,
            },
            verified=False,
            business_ok=False,
            note=f"#{product_id} 上传失败 - {err_msg[:160]}",
        )
        return

    product_repo.update(product_id, {
        "alipay_image_material_id": material_id,
        "alipay_image_source": source_signature,
    })
    notify_record(
        channel="alipay_material_upload",
        params={
            "product_id":   product_id,
            "product_name": p.get("name") or "",
            "outcome":      "uploaded",
            "cover":        new_cover,
            "material_id":  material_id,
        },
        verified=True,
        business_ok=True,
        note=f"#{product_id} 上传成功 → material_id={material_id}",
    )


# ---------- 通用 CRUD 工厂 ----------
def _register_crud(prefix: str, repo):
    @bp.get(f"/{prefix}", endpoint=f"{prefix}_list")
    def _list():
        items = repo.list()
        return ok({"list": items, "total": len(items)})

    @bp.get(f"/{prefix}/<int:oid>", endpoint=f"{prefix}_get")
    def _get(oid):
        item = repo.get(oid)
        if not item:
            return fail(404, "记录不存在")
        return ok(item)

    @bp.post(f"/{prefix}", endpoint=f"{prefix}_create")
    def _create():
        body, dropped = _sanitize(prefix, request.get_json(silent=True))
        if prefix == "products":
            err = _validate_product_deposit(body, required=True)
            if err:
                return fail(1, err)
            err = _validate_product_pricing(body, required=True)
            if err:
                return fail(1, err)
            if "price_tiers" in body:
                okp, errmsg = validate_tiers(body["price_tiers"])
                if not okp:
                    return fail(1, f"价格分段配置无效：{errmsg}")
                _apply_pricing_derivations(body)
            _apply_product_covers_sync(body)
            _apply_damage_standard_normalize(body)
        rec = repo.create(body)
        # 商品的封面图变更时，自动把主图上传到支付宝素材库 → 写回 material_id
        # 失败不抛错；下次保存还会再试
        if prefix == "products" and rec and rec.get("id"):
            _sync_product_alipay_material(rec["id"])
            rec = repo.get(rec["id"]) or rec  # 拿回带最新 material_id 的视图
        msg = "新增成功"
        if dropped:
            msg += f"（已忽略字段：{', '.join(dropped)}）"
        return ok(rec, msg)

    @bp.put(f"/{prefix}/<int:oid>", endpoint=f"{prefix}_update")
    def _update(oid):
        body, dropped = _sanitize(prefix, request.get_json(silent=True))
        if prefix == "products":
            err = _validate_product_deposit(body, required=False)
            if err:
                return fail(1, err)
            err = _validate_product_pricing(body, required=False)
            if err:
                return fail(1, err)
            if "price_tiers" in body:
                okp, errmsg = validate_tiers(body["price_tiers"])
                if not okp:
                    return fail(1, f"价格分段配置无效：{errmsg}")
                _apply_pricing_derivations(body)
            _apply_product_covers_sync(body)
            _apply_damage_standard_normalize(body)
        rec = repo.update(oid, body)
        if not rec:
            return fail(404, "记录不存在")
        # 商品保存后同步触发素材上传（封面没变会自动 skip）
        if prefix == "products":
            _sync_product_alipay_material(oid)
            rec = repo.get(oid) or rec
        msg = "更新成功"
        if dropped:
            msg += f"（已忽略字段：{', '.join(dropped)}）"
        return ok(rec, msg)

    @bp.delete(f"/{prefix}/<int:oid>", endpoint=f"{prefix}_delete")
    def _delete(oid):
        if not repo.delete(oid):
            return fail(404, "记录不存在")
        return ok(None, "删除成功")


_register_crud("banners", banner_repo)
_register_crud("categories", category_repo)
_register_crud("products", product_repo)
_register_crud("faqs", faq_repo)


# ---------- 优惠券（满减券）独立 CRUD（带满减专属校验） ----------
def _validate_coupon(body: dict, *, required: bool) -> str | None:
    """满减券核心校验：threshold > 0 且 >= discount > 0；时间段合法。"""
    def _num(key):
        try:
            return float(body.get(key) or 0)
        except (TypeError, ValueError):
            return None

    if "threshold" in body or "discount" in body or required:
        threshold = _num("threshold")
        discount = _num("discount")
        if threshold is None or discount is None:
            return "门槛 / 减免金额必须为数字"
        if threshold <= 0:
            return "满减门槛必须大于 0"
        if discount <= 0:
            return "减免金额必须大于 0"
        if discount > threshold:
            return "减免金额不能大于门槛（避免负数订单）"
    if "name" in body or required:
        if not (body.get("name") or "").strip():
            return "请填写优惠券名称"
    start = int(body.get("start_at") or 0)
    end = int(body.get("end_at") or 0)
    if start and end and end < start:
        return "结束时间不能早于开始时间"
    if "status" in body and body["status"] not in ("on", "off"):
        return "状态必须是 on 或 off"
    return None


@bp.get("/coupons", endpoint="coupons_list")
def coupons_list():
    items = coupon_repo.list()
    # 新建的排前面（与其它资源一致：按 updated_at 倒序，便于刚改完立刻看到）
    items.sort(key=lambda x: -int(x.get("updated_at") or 0))
    return ok({"list": items, "total": len(items)})


@bp.get("/coupons/<int:cid>", endpoint="coupons_get")
def coupons_get(cid):
    item = coupon_repo.get(cid)
    if not item:
        return fail(404, "优惠券不存在")
    return ok(item)


@bp.post("/coupons", endpoint="coupons_create")
def coupons_create():
    body, dropped = _sanitize("coupons", request.get_json(silent=True))
    err = _validate_coupon(body, required=True)
    if err:
        return fail(1, err)
    body.setdefault("status", "on")
    rec = coupon_repo.create(body)
    msg = "新增成功"
    if dropped:
        msg += f"（已忽略字段：{', '.join(dropped)}）"
    return ok(rec, msg)


@bp.put("/coupons/<int:cid>", endpoint="coupons_update")
def coupons_update(cid):
    body, dropped = _sanitize("coupons", request.get_json(silent=True))
    err = _validate_coupon(body, required=False)
    if err:
        return fail(1, err)
    rec = coupon_repo.update(cid, body)
    if not rec:
        return fail(404, "优惠券不存在")
    msg = "更新成功"
    if dropped:
        msg += f"（已忽略字段：{', '.join(dropped)}）"
    return ok(rec, msg)


@bp.delete("/coupons/<int:cid>", endpoint="coupons_delete")
def coupons_delete(cid):
    if not coupon_repo.delete(cid):
        return fail(404, "优惠券不存在")
    return ok(None, "删除成功")


@bp.get("/coupons/<int:cid>/grants")
def coupons_grants(cid):
    """查看某张券的领取明细（运营查看核销情况用）。"""
    items = user_coupon_repo.list(coupon_id=cid)
    items.sort(key=lambda x: -int(x.get("claimed_at") or 0))
    return ok({"list": items, "total": len(items)})


# ---------- 订单管理 ----------
# 订单状态机（与小程序端 ORDER_STATUS_TABS 保持一致）：
#   audit → send → recv → using → return → done
#                                      ↘ overdue ↗
#   audit / send / recv → cancelled（取消并退押）
# 注：芝麻免押本身已含活体校验，二次人脸冗余，原 awaiting_face 环节已废弃。
_ADMIN_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "audit":             {"cancelled"},                          # 取消未付押的订单
    "send":              {"recv", "pending_cancel", "cancelled"},# 发货 / 用户申请取消 / 强制取消
    "pending_cancel":    {"send", "cancelled"},                  # 商家驳回回 send / 同意取消
    "recv":              {"using", "cancelled"},                 # 标记用户已签收 / 退货
    "using":             {"return", "overdue", "return_inspecting", "done"},
    "return":            {"return_inspecting", "done", "overdue"},
    "overdue":           {"return", "return_inspecting", "done"},
    "return_inspecting": {"done", "return"},                     # 核验通过 → done；驳回退回 return
    "done":              set(),                                  # 终态不允许再改
    "cancelled":         set(),                                  # 终态不允许再改
}

_ORDER_STATUS_LABEL = {
    "audit":             "待免押",
    "send":              "待发货",
    "pending_cancel":    "取消审核中",
    "recv":              "待收货",
    "using":             "租赁中",
    "return":            "待归还",
    "overdue":           "已逾期",
    "return_inspecting": "核验中",
    "done":              "已完成",
    "cancelled":         "已取消",
}


# 芝麻免押授权有效期：360 天后支付宝自动解冻，无法再扣款；剩余 60 天内前端标红提示运营尽快处理
_FREEZE_VALIDITY_DAYS = 360
_FREEZE_WARN_DAYS = 60
# 终态：解冻已完成，无需再追押金倒计时
_FREEZE_DONE_STATUS = frozenset({"done", "cancelled"})


def _attach_freeze_countdown(out: dict, o: dict) -> None:
    """计算押金授权剩余天数。
    起点取 send_at（freeze→audit 通过的落地时间）；若缺失但 auth_no 已存在，
    退回 created_at 作兜底，避免没有起点导致前端一直显示空白。
    """
    if not o.get("alipay_auth_no") or (o.get("status") or "") in _FREEZE_DONE_STATUS:
        out["freeze_active"] = False
        return
    start = int(o.get("send_at") or 0) or int(o.get("created_at") or 0)
    if not start:
        out["freeze_active"] = False
        return
    expire_at = start + _FREEZE_VALIDITY_DAYS * 86400
    now = int(time.time())
    days_left = (expire_at - now) // 86400  # 向下取整：剩 0.x 天显示 0
    out["freeze_active"]         = True
    out["freeze_start_at"]       = start
    out["freeze_expire_at"]      = expire_at
    out["freeze_expire_at_text"] = time.strftime("%Y-%m-%d", time.localtime(expire_at))
    out["freeze_days_left"]      = int(days_left)
    out["freeze_warn"]           = 0 < days_left <= _FREEZE_WARN_DAYS
    out["freeze_expired"]        = days_left <= 0


def _note_view(n: dict) -> dict:
    """单条订单备注的展示视图：补「修改时间」可读字符串。"""
    out = dict(n)
    ts = int(n.get("created_at") or 0)
    out["created_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
    )
    return out


def _latest_note_for(order_id, note_map: dict | None = None) -> dict | None:
    """取某订单最新一条备注（按 created_at 倒序）。
    note_map 传入时走预加载（列表批量场景，避免逐行查库）；否则现查。
    """
    if note_map is not None:
        return note_map.get(order_id)
    notes = order_note_repo.list(order_id=order_id)
    if not notes:
        return None
    latest = max(notes, key=lambda x: int(x.get("created_at") or 0))
    return _note_view(latest)


def _order_view(o: dict, *, user_map: dict | None = None,
                product_map: dict | None = None,
                note_map: dict | None = None) -> dict:
    """订单列表/详情统一视图：补 user_nickname / product_cover / status_label / 时间字符串。"""
    out = dict(o)
    ts = int(o.get("created_at") or 0)
    out["created_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
    )
    upd = int(o.get("updated_at") or 0)
    out["updated_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(upd)) if upd else ""
    )
    out["status_label"] = _ORDER_STATUS_LABEL.get(o.get("status") or "", o.get("status") or "")
    # pending_cancel 细分：商家已点同意并下发解冻请求 → "解冻中"，未审核 → 保留 "取消审核中"
    if o.get("status") == "pending_cancel" and o.get("unfreeze_dispatched_at"):
        out["status_label"] = "解冻中"
    # return_inspecting 细分：商家已点核验通过并下发解冻请求 → "解冻中"
    if o.get("status") == "return_inspecting" and o.get("unfreeze_dispatched_at"):
        out["status_label"] = "解冻中"

    uid = o.get("user_id") or ""
    if user_map is not None:
        u = user_map.get(uid) or {}
    else:
        u = user_repo.get(uid) or {} if uid else {}
    out["user_nickname"] = u.get("nickname") or ""
    out["user_real_name"] = u.get("real_name") or ""
    out["user_phone"] = u.get("phone") or ""
    out["user_verified"] = bool(u.get("verified"))

    pid = o.get("product_id")
    if product_map is not None:
        p = product_map.get(pid) or {}
    else:
        p = product_repo.get(pid) or {} if pid else {}
    # 部分老商品只填了 covers[] 没回填 cover_url，这里按 Products.vue 一样的顺序兜底
    covers = p.get("covers") if isinstance(p.get("covers"), list) else []
    out["product_cover"] = (covers[0] if covers else "") or (p.get("cover_url") or "")

    # 物流展示字段：把内部编码翻译成中文名 + 发货时间字符串
    lc = (o.get("logistics_company") or "").upper()
    courier = logistics.get(lc) if lc else None
    out["logistics_company_name"] = courier.name if courier else (lc or "")
    sh = int(o.get("shipped_at") or 0)
    out["shipped_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sh)) if sh else ""
    )

    # 归还物流（用户寄回）
    rlc = (o.get("return_logistics_company") or "").upper()
    rcourier = logistics.get(rlc) if rlc else None
    out["return_logistics_company_name"] = rcourier.name if rcourier else (rlc or "")
    ra = int(o.get("returned_at") or 0)
    out["returned_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ra)) if ra else ""
    )

    # 支付宝商家订单同步状态：把 unix ts 翻译成可读字符串
    sa = int(o.get("sync_at") or 0)
    out["sync_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sa)) if sa else ""
    )

    # 押金授权 360 天倒计时（剩余 ≤60 天前端标红）
    _attach_freeze_countdown(out, o)

    # 工作人员备注：列表/详情都带上最新一条，便于「简洁显示最新备注」
    out["latest_note"] = _latest_note_for(o.get("id"), note_map)

    # 租赁平台（淘宝观澜/闲鱼…）：从发货时的光影快照里派生，列表/详情统一展示。
    # 支付宝只是收押金的手段、不算平台；真正的渠道存在光影 rent_record.rent_platform。
    out["rent_platform"] = _rent_platform_of(o)
    return out


def _rent_platform_of(o: dict) -> str:
    """从订单的光影发货快照里取「在租平台」：优先 current_rent，兜底最近一条 ship_out。"""
    snap = o.get("item_snapshot") or {}
    if not isinstance(snap, dict):
        return ""
    cur = snap.get("current_rent") or {}
    if isinstance(cur, dict):
        plat = (cur.get("rent_platform") or "").strip()
        if plat:
            return plat
    for r in (snap.get("rent_records") or []):
        if isinstance(r, dict) and r.get("action") == "ship_out":
            plat = (r.get("rent_platform") or "").strip()
            if plat:
                return plat
    return ""


# ---------- 光影库存系统对接 ----------
@bp.get("/inventory/item")
def admin_inventory_item():
    """按货号查光影库存系统商品卡片（服务端代理，特权 Token 不暴露给浏览器）。

    返回 data：
      lookup_status: ok / not_configured / not_found / error
      item:          lookup_status=ok 时的商品卡片 dict，其余为 None
      message:       非 ok 时的提示文案
    """
    from app import inventory_client
    huohao = (request.args.get("huohao") or "").strip()
    if not huohao:
        return fail(1, "请填写货号")
    status, payload = inventory_client.fetch_item_by_huohao(huohao)
    return ok({
        "lookup_status": status,
        "item": payload if status == inventory_client.STATUS_OK else None,
        "message": "" if status == inventory_client.STATUS_OK else payload,
    })


@bp.get("/ui-config")
def admin_ui_config():
    """非敏感 UI 标志，operator 也可读（settings 本体仅 admin 可见）。"""
    from app import inventory_client
    from app.settings import get as settings_get
    return ok({
        "ship_huohao_required": bool(settings_get("ship_huohao_required")),
        "inventory_sync_configured": inventory_client.is_configured(),
    })


# ---------- 发货 ----------
@bp.get("/logistics/identify")
def logistics_identify():
    """运单号 → 快递公司识别，前端在输入框 onChange 里调用。
    返回 {code, name, alipay_code}：code=unknown 时前端应要求人工选择。
    """
    no = (request.args.get("no") or "").strip()
    c = logistics.identify(no)
    return ok({
        **c.to_dict(),
        "input_normalized": logistics.normalize_no(no),
    })


@bp.get("/logistics/couriers")
def logistics_couriers():
    """支持的快递公司列表，前端下拉框用。"""
    return ok({"list": logistics.supported_list()})


@bp.post("/orders/<oid>/ship")
def admin_ship_order(oid):
    """发货：写入运单 + 状态 send → recv。

    入参（JSON）：
      logistics_no       必填，运单号
      logistics_company  可选，若不传则按 logistics_no 自动识别；
                         自动识别失败（unknown）必须由前端补传该字段。
      huohao             光影库存系统货号；选填/必填由 settings.ship_huohao_required 决定。
                         填了则发货时拉取商品卡片快照存到订单（拉取失败不阻断发货）。
    """
    from app import inventory_client
    from app.settings import get as settings_get

    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("status") != "send":
        cur_label = _ORDER_STATUS_LABEL.get(o.get("status") or "", o.get("status") or "")
        return fail(1, f"仅「待发货」状态可发货，当前为「{cur_label}」")

    body = request.get_json(silent=True) or {}
    logistics_no = logistics.normalize_no(body.get("logistics_no") or "")
    if not logistics_no:
        return fail(1, "请填写运单号")

    huohao = (body.get("huohao") or "").strip()
    if settings_get("ship_huohao_required") and not huohao:
        return fail(1, "当前设置要求发货时必须填写货号")

    company_input = (body.get("logistics_company") or "").strip().upper()
    if company_input:
        # 前端传了公司：要求是支持的，且与运单号识别结果一致（识别为 unknown 时放行）
        if not logistics.is_supported(company_input):
            return fail(1, f"暂不支持的快递公司：{company_input}（目前只支持顺丰 SF / 京东 JD）")
        detected = logistics.identify(logistics_no)
        if detected.code != "unknown" and detected.code != company_input:
            return fail(
                1,
                f"运单号「{logistics_no}」看起来是{detected.name}的格式，"
                f"与所选快递公司「{logistics.get(company_input).name}」不一致，请核对",
            )
        company = company_input
    else:
        # 前端没传公司：必须能自动识别出来
        detected = logistics.identify(logistics_no)
        if detected.code == "unknown":
            return fail(
                1,
                "无法根据运单号自动识别快递公司，请手动选择（目前仅支持顺丰、京东）",
            )
        company = detected.code

    patch = {
        "status":            "recv",
        "logistics_company": company,
        "logistics_no":      logistics_no,
        "shipped_at":        int(time.time()),
        "lock_until":        None,
    }
    if huohao:
        # 拉取商品卡片快照；失败（未配置/未找到/网络）不阻断发货，仅落空快照
        lookup_status, payload = inventory_client.fetch_item_by_huohao(huohao)
        patch["item_huohao"] = huohao
        patch["item_snapshot"] = payload if lookup_status == inventory_client.STATUS_OK else {}
    # status 变成 recv 时拦截器会自动调 sync_order；sync 结果（成功/失败）会被
    # 同步写回订单的 sync_ok / sync_err 字段，再读一次给运营看精确消息。
    update_order(oid, patch, sync_reason="shipped")
    fresh = order_repo.get(oid)
    if fresh.get("sync_ok"):
        msg = "已发货并同步至支付宝"
    else:
        msg = f"已发货，支付宝同步失败（可重试）：{(fresh.get('sync_err') or '')[:80]}"
    return ok(_order_view(fresh), msg)


@bp.post("/orders/<oid>/sync")
def admin_resync_order(oid):
    """手动重试支付宝商家订单同步。失败也返回 200，错误信息走 msg。"""
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    from app import order_sync
    sync_ok, sync_err = order_sync.sync_order(oid, reason="manual_retry")
    fresh = order_repo.get(oid)
    if sync_ok:
        return ok(_order_view(fresh), "已同步至支付宝")
    return ok(_order_view(fresh), f"同步失败：{sync_err[:120]}")


@bp.get("/orders")
def admin_list_orders():
    """订单列表：支持 ?status= / ?user_id= / ?product_id= / ?keyword= 过滤。
    keyword 模糊匹配 订单号 / 商品名 / 收货人姓名 / 收货人手机号。
    """
    status     = (request.args.get("status") or "").strip()
    user_id    = (request.args.get("user_id") or "").strip()
    product_id = request.args.get("product_id", type=int)
    keyword    = (request.args.get("keyword") or "").strip().lower()

    items = order_repo.list()
    if status and status != "all":
        items = [o for o in items if (o.get("status") or "") == status]
    if user_id:
        items = [o for o in items if (o.get("user_id") or "") == user_id]
    if product_id:
        items = [o for o in items if int(o.get("product_id") or 0) == product_id]
    if keyword:
        def _hit(o: dict) -> bool:
            addr = o.get("address_snapshot") or {}
            blob = " ".join([
                str(o.get("id") or ""),
                str(o.get("product_name") or ""),
                str(addr.get("receiver_name") or ""),
                str(addr.get("receiver_phone") or ""),
                str(o.get("user_id") or ""),
            ]).lower()
            return keyword in blob
        items = [o for o in items if _hit(o)]

    items.sort(key=lambda x: -int(x.get("created_at") or 0))

    # 批量预加载关联表，避免列表里每行各查一次
    uids = {o.get("user_id") for o in items if o.get("user_id")}
    user_map = {u["id"]: u for u in user_repo.list() if u["id"] in uids} if uids else {}
    pids = {o.get("product_id") for o in items if o.get("product_id")}
    product_map = {p["id"]: p for p in product_repo.list() if p["id"] in pids} if pids else {}

    # 备注批量预加载：一次拉全表，按 order_id 归并出「每单最新一条」，避免逐行查库
    oids = {o.get("id") for o in items if o.get("id")}
    note_map: dict = {}
    if oids:
        for n in order_note_repo.list():
            oid = n.get("order_id")
            if oid not in oids:
                continue
            cur = note_map.get(oid)
            if cur is None or int(n.get("created_at") or 0) > int(cur.get("created_at") or 0):
                note_map[oid] = n
        note_map = {k: _note_view(v) for k, v in note_map.items()}

    return ok({
        "list":  [_order_view(o, user_map=user_map, product_map=product_map,
                              note_map=note_map) for o in items],
        "total": len(items),
    })


@bp.get("/orders/stats")
def admin_orders_stats():
    """按状态分组的订单计数 + 总额，供顶部 tab 角标显示。"""
    items = order_repo.list()
    by_status: dict[str, int] = {k: 0 for k in _ORDER_STATUS_LABEL}
    revenue = 0.0
    for o in items:
        s = o.get("status") or ""
        by_status[s] = by_status.get(s, 0) + 1
        if s not in ("audit", "cancelled"):
            revenue += float(o.get("amount") or 0)
    return ok({
        "total":     len(items),
        "by_status": by_status,
        "revenue":   round(revenue, 2),
    })


@bp.get("/orders/<oid>")
def admin_get_order(oid):
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    detail = _order_view(o)
    # 详情页额外拼一份完整地址，省得前端再去拉
    if o.get("address_id"):
        addr = address_repo.get(o["address_id"])
        if addr:
            detail["address_full"] = addr
    # 优惠券领取实例（用于追溯）
    if o.get("user_coupon_id"):
        detail["coupon_grant"] = user_coupon_repo.get(o["user_coupon_id"])
    return ok(detail)


# ---------- 订单备注（仅工作人员可见的独立审计日志） ----------
@bp.get("/orders/<oid>/notes")
def admin_list_order_notes(oid):
    """某订单的全部工作人员备注，按修改时间倒序（最新在前）。"""
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    notes = order_note_repo.list(order_id=oid)
    notes.sort(key=lambda x: -int(x.get("created_at") or 0))
    return ok({
        "list":  [_note_view(n) for n in notes],
        "total": len(notes),
    })


@bp.post("/orders/<oid>/notes")
def admin_create_order_note(oid):
    """追加一条订单备注。每条都是独立不可变记录，自动落「修改人 + 修改时间」。"""
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    body = request.get_json(silent=True) or {}
    content = (body.get("content") or "").strip()
    if not content:
        return fail(1, "请填写备注内容")
    if len(content) > 1000:
        return fail(1, "备注内容过长（最多 1000 字）")

    staff = getattr(g, "staff", None) or {}
    rec = order_note_repo.create({
        "order_id":        oid,
        "content":         content,
        "staff_id":        staff.get("id"),
        "staff_username":  staff.get("username") or "",
        "staff_real_name": staff.get("real_name") or "",
    })
    return ok(_note_view(rec), "备注已添加")


@bp.put("/orders/<oid>")
def admin_update_order(oid):
    """订单更新：当前仅允许改 status / remark。状态流转走白名单，
    误操作（如把 send 打回 audit）会被拒；admin 想强改请传 force=true。
    """
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    body = request.get_json(silent=True) or {}
    patch: dict = {}

    new_status = (body.get("status") or "").strip()
    if new_status:
        if new_status not in _ORDER_STATUS_LABEL:
            return fail(1, f"非法状态：{new_status}")
        cur = o.get("status") or ""
        if new_status != cur:
            allowed = _ADMIN_ORDER_TRANSITIONS.get(cur, set())
            if new_status not in allowed and not body.get("force"):
                return fail(
                    1,
                    f"不允许从「{_ORDER_STATUS_LABEL.get(cur, cur)}」流转到"
                    f"「{_ORDER_STATUS_LABEL.get(new_status, new_status)}」"
                    f"（如确需强制修改请勾选「强制修改」）",
                )
            patch["status"] = new_status
            # 进入 send 后锁库倒计时已无意义，清掉避免列表展示残留
            if new_status in ("send", "recv", "using", "return", "overdue", "done"):
                patch["lock_until"] = None
            # 后台强制流转到 send 时也补 send_at，保证前端 48h 发货倒计时有基准
            if new_status == "send" and not o.get("send_at"):
                patch["send_at"] = int(time.time())
            # 手工把订单推进到 using（recv → using）时补 lease_started_at；
            # 阿里同步的 business_info.receiving_time 依赖这个字段，
            # 缺了会导致 SERVICE_MSG（订单消息）分发失败。
            if new_status == "using" and not o.get("lease_started_at"):
                patch["lease_started_at"] = int(time.time())

    if "remark" in body:
        patch["remark"] = (body.get("remark") or "").strip()

    if not patch:
        return fail(1, "没有要修改的字段")

    # status 变更会被 update_order 拦截器自动同步到支付宝订单中心；
    # 失败不回滚业务变更，sync_err 字段会被写好，前端可走"重试同步"。
    update_order(oid, patch, sync_reason="admin_status_update")
    updated = order_repo.get(oid)  # 拿回带最新 sync_* 字段的视图
    sync_msg = ""
    if "status" in patch and not updated.get("sync_ok"):
        sync_msg = f"（支付宝同步失败，可重试：{(updated.get('sync_err') or '')[:80]}）"
    return ok(_order_view(updated), "已更新" + sync_msg)


# ---------- 商家审核用户取消申请（send → pending_cancel → cancelled / send） ----------
@bp.post("/orders/<oid>/cancel-approve")
def admin_cancel_approve(oid):
    """同意用户的取消申请：调 alipay.fund.auth.order.unfreeze 下发解冻请求。

    保守模式：本接口只把解冻请求发出去并打上时间戳，订单状态仍停在
    pending_cancel；真正的终态推进（→ cancelled / 退优惠券 / sync 订单中心）
    放在异步 notify 回调 transition_unfreeze_done 里做，避免"本端已 cancelled
    但支付宝那边解冻失败"的状态错位。
    """
    from app.alipay_client import get_client
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("status") != "pending_cancel":
        return fail(1, f"订单当前状态 {o.get('status')}，不能同意取消")
    if o.get("unfreeze_dispatched_at"):
        return fail(1, "已下发过解冻请求，等待支付宝异步通知")

    auth_no = (o.get("alipay_auth_no") or "").strip()
    # 实际可解冻 = 冻结池 - 已扣款（refund 不补回，不参与计算）
    amount  = _calc_unfreezable_amount(o)
    remark  = "商家同意用户取消申请，解冻剩余冻结额度"
    now = int(time.time())

    if not auth_no:
        # 历史数据：没有真实授权号，无法调支付宝，直接走本地终态推进
        from app.routes.orders import transition_unfreeze_done
        updated = transition_unfreeze_done(oid)
        return ok(_order_view(updated or o), "无支付宝授权号，已本地直接关单")

    if amount <= 0:
        # 冻结池已经被扣款消耗完（alipay 不接受 0 元解冻），本地直接关单
        from app.routes.orders import transition_unfreeze_done
        updated = transition_unfreeze_done(oid)
        return ok(_order_view(updated or o),
                  "冻结额度已被扣款全部消耗，无可解冻金额，本地直接关单")

    out_request_no = "UF" + uuid.uuid4().hex[:18].upper()
    try:
        get_client().auth_unfreeze(
            auth_no=auth_no,
            out_request_no=out_request_no,
            amount=amount,
            remark=remark,
        )
    except Exception as e:
        return fail(1, f"调用 alipay 解冻失败：{e}")

    # status 没变（pending_cancel→pending_cancel），update_order 拦截器看到不 sync
    updated = update_order(oid, {
        "cancel_approved_at":      now,
        "unfreeze_dispatched_at":  now,
        "unfreeze_out_request_no": out_request_no,
        "unfreeze_amount":         amount,   # 实际下发的解冻金额，方便后续排查
    })
    return ok(_order_view(updated), f"已同意，已下发解冻请求 ¥{amount:.2f}，等待支付宝通知")


@bp.post("/orders/<oid>/cancel-reject")
def admin_cancel_reject(oid):
    """驳回用户的取消申请：状态回到 send（商家继续发货）。"""
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("status") != "pending_cancel":
        return fail(1, f"订单当前状态 {o.get('status')}，无取消申请可驳回")
    body = request.get_json(silent=True) or {}
    reject_reason = (body.get("reason") or "").strip()
    # status: pending_cancel→send，拦截器自动 sync 到支付宝订单中心（→ TO_SEND_GOODS）
    updated = update_order(oid, {
        "status": "send",
        "cancel_reject_reason": reject_reason,
        "cancel_rejected_at": int(time.time()),
    }, sync_reason="admin_cancel_reject")
    return ok(_order_view(updated), "已驳回，订单回到待发货")


# ---------- 商家代用户填写寄回快递信息（using/return/overdue → return_inspecting） ----------
@bp.post("/orders/<oid>/return-ship")
def admin_return_ship(oid):
    """客服代用户填写寄回快递信息（场景：用户在小程序里不操作、私聊客服处理）。

    与用户端 POST /api/orders/<oid>/return-ship 的状态机完全一致，区别仅在于：
      - 不校验 current_user 是否订单归属人
      - 落 returned_by 标记为 "admin:<staff_username>" 便于后续追溯

    Body:
      logistics_company  必填，SF / JD（与 admin.logistics.SUPPORTED 一致）
      logistics_no       必填，运单号

    提交后订单进入 return_inspecting，由商家后续点「核验通过」走标准 unfreeze 链路。
    """
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")

    status = o.get("status") or ""
    if status not in ("using", "return", "overdue"):
        cur = _ORDER_STATUS_LABEL.get(status, status)
        return fail(1, f"订单当前状态「{cur}」不能发起归还")

    body = request.get_json(silent=True) or {}
    logistics_no = logistics.normalize_no(body.get("logistics_no") or "")
    company_input = (body.get("logistics_company") or "").strip().upper()
    if not logistics_no:
        return fail(1, "请填写运单号")
    if not company_input or not logistics.is_supported(company_input):
        return fail(1, "请选择有效的快递公司（目前仅支持顺丰 SF / 京东 JD）")

    # 运单号若能被识别出快递公司，必须与所选一致（避免选错导致核验找不到包裹）
    detected = logistics.identify(logistics_no)
    if detected.code != "unknown" and detected.code != company_input:
        return fail(
            1,
            f"运单号「{logistics_no}」看起来是{detected.name}的格式，"
            f"与所选快递公司不一致，请核对",
        )

    now = int(time.time())
    operator = (g.staff.get("username") or "admin") if hasattr(g, "staff") and g.staff else "admin"
    updated = update_order(oid, {
        "status":                   "return_inspecting",
        "return_logistics_company": company_input,
        "return_logistics_no":      logistics_no,
        "returned_at":              now,
        "returned_by":              f"admin:{operator}",
        # 上一次可能存在的驳回理由清掉，避免和这次代填混在一起展示
        "return_reject_reason":     "",
        "return_rejected_at":       None,
    }, sync_reason="admin_return_ship")
    return ok(_order_view(updated), f"已代用户提交寄回信息（{company_input} / {logistics_no}），订单进入核验中")


# ---------- 商家核验用户寄回归还（return_inspecting → done） ----------
@bp.post("/orders/<oid>/return-approve")
def admin_return_approve(oid):
    """同意用户归还：调 alipay.fund.auth.order.unfreeze 全额解冻。

    与 cancel-approve 同样的保守策略：本接口只下发解冻请求并打时间戳，
    订单仍停在 return_inspecting；真正的终态推进（→ done）由异步 notify
    回调 transition_unfreeze_done 完成。
    """
    from app.alipay_client import get_client
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("status") != "return_inspecting":
        cur = _ORDER_STATUS_LABEL.get(o.get("status") or "", o.get("status") or "")
        return fail(1, f"订单当前状态「{cur}」，不能核验通过")
    if o.get("unfreeze_dispatched_at"):
        return fail(1, "已下发过解冻请求，等待支付宝异步通知")

    auth_no = (o.get("alipay_auth_no") or "").strip()
    amount  = _calc_unfreezable_amount(o)
    remark  = "商家核验通过，解冻剩余冻结额度"
    now = int(time.time())

    if not auth_no:
        from app.routes.orders import transition_unfreeze_done
        updated = transition_unfreeze_done(oid)
        return ok(_order_view(updated or o), "无支付宝授权号，已本地直接关单")

    if amount <= 0:
        from app.routes.orders import transition_unfreeze_done
        updated = transition_unfreeze_done(oid)
        return ok(_order_view(updated or o),
                  "冻结额度已被扣款全部消耗，无可解冻金额，本地直接关单")

    out_request_no = "UF" + uuid.uuid4().hex[:18].upper()
    try:
        get_client().auth_unfreeze(
            auth_no=auth_no,
            out_request_no=out_request_no,
            amount=amount,
            remark=remark,
        )
    except Exception as e:
        return fail(1, f"调用 alipay 解冻失败：{e}")

    # status 没变（return_inspecting→return_inspecting），update_order 不触发 sync
    updated = update_order(oid, {
        "return_approved_at":      now,
        "unfreeze_dispatched_at":  now,
        "unfreeze_out_request_no": out_request_no,
        "unfreeze_amount":         amount,
    })
    return ok(_order_view(updated), f"已核验通过，已下发解冻请求 ¥{amount:.2f}，等待支付宝通知")


@bp.post("/orders/<oid>/return-reject")
def admin_return_reject(oid):
    """驳回用户的归还（运单号查无包裹等）：状态回到 return（用户重新填）。"""
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    if o.get("status") != "return_inspecting":
        return fail(1, f"订单当前状态 {o.get('status')}，无归还核验可驳回")
    body = request.get_json(silent=True) or {}
    reject_reason = (body.get("reason") or "").strip()
    # status: return_inspecting→return，拦截器自动 sync 到支付宝订单中心（→ RENT_DUE）
    updated = update_order(oid, {
        "status": "return",
        "return_reject_reason": reject_reason,
        "return_rejected_at":  int(time.time()),
        # 清掉用户上次填的快递信息，强制重新填
        "return_logistics_company": "",
        "return_logistics_no":      "",
        "returned_at":              None,
    }, sync_reason="admin_return_reject")
    return ok(_order_view(updated), "已驳回，订单回到待归还，请用户重新填写寄回信息")


@bp.delete("/orders/<oid>")
def admin_delete_order(oid):
    """删除订单。终态（done）允许直接删；进行中的订单要求 force=true，
    防止运营误把活跃订单删掉导致退押无据可循。
    """
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    force = request.args.get("force") in ("1", "true", "True")
    if o.get("status") not in ("done", "cancelled") and not force:
        return fail(1, "仅已完成 / 已取消订单可直接删除；如确需删除请使用强制删除")
    order_repo.delete(oid)
    return ok(None, "已删除")


# ---------- 用户 ----------
# 进行中订单状态：与 stats 接口口径一致（done / cancelled 为终态）
_ORDER_IN_PROGRESS = frozenset({"audit", "send", "recv", "using", "return", "overdue"})


@bp.get("/users")
def list_users():
    users = user_repo.list()
    # 聚合每个用户的下单数 / 最近下单时间 / 是否有进行中订单，避免前端逐条拉
    order_count: dict[str, int] = {}
    last_order_ts: dict[str, int] = {}
    has_active: dict[str, bool] = {}
    for o in order_repo.list():
        uid = o.get("user_id") or ""
        if not uid:
            continue
        order_count[uid] = order_count.get(uid, 0) + 1
        ts = int(o.get("created_at") or 0)
        if ts > last_order_ts.get(uid, 0):
            last_order_ts[uid] = ts
        if (o.get("status") or "") in _ORDER_IN_PROGRESS:
            has_active[uid] = True

    enriched = []
    for u in users:
        uid = u.get("id")
        ts = last_order_ts.get(uid, 0)
        reg_ts = int(u.get("created_at") or 0)   # 用户注册时间（首次登录入库时由 BaseRepository 写入）
        enriched.append({
            **u,
            "order_count": order_count.get(uid, 0),
            "last_order_at": ts,
            "last_order_at_text": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
            ),
            "created_at_text": (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reg_ts)) if reg_ts else ""
            ),
            "has_active_order": bool(has_active.get(uid)),
        })
    return ok({"list": enriched, "total": len(enriched)})


# ---------- 支付宝回调日志（临时观察用） ----------
@bp.get("/notify-logs")
def notify_logs():
    """返回最近的 notify 记录。
    ?since=毫秒时间戳   增量轮询用
    ?channel=auth_freeze 精确通道过滤
    ?prefix=gateway:    前缀过滤（如网关消息一组）
    """
    since = request.args.get("since", type=int) or 0
    channel = request.args.get("channel") or ""
    prefix = request.args.get("prefix") or ""
    limit = min(request.args.get("limit", default=200, type=int), 500)
    items = list_notify_logs(since_ts=since, channel=channel,
                             channel_prefix=prefix, limit=limit)
    return ok({"list": items, "total": len(items)})


# ---------- 订单维度的支付宝授权资金明细查询 ----------
@bp.get("/orders/<oid>/alipay-detail")
def order_alipay_detail(oid):
    """调 alipay.fund.auth.operation.detail.query 拿订单的授权资金明细。
    返回 pre_auth_type=CREDIT_AUTH 即为信用免押；order_status / status 反映授权单状态。
    """
    from app.storage.repos import order_repo
    from app.alipay_client import get_client

    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")

    out_request_no = (o.get("alipay_out_request_no") or "").strip()
    auth_no        = (o.get("alipay_auth_no") or "").strip()
    operation_id   = (o.get("alipay_operation_id") or "").strip()
    operation_type = (request.args.get("operation_type") or "FREEZE").upper()
    # 重试冻结后支付宝侧授权订单号带后缀，必须用当前生效号配对查询；老订单无该字段→回退裸号
    active_oon     = (o.get("alipay_out_order_no") or "").strip() or oid

    # 没有任何配对参数 → 订单还没发起过 freeze，直接返回空
    if not out_request_no and not auth_no:
        return ok({
            "found": False,
            "reason": "订单还未发起过支付宝预授权（缺 out_request_no / auth_no）",
            "out_order_no": active_oon,
        })

    try:
        res = get_client().auth_operation_detail_query(
            out_order_no=active_oon,
            out_request_no=out_request_no or None,
            auth_no=auth_no or None,
            operation_id=operation_id or None,
            operation_type=operation_type,
        )
    except Exception as e:
        return fail(10009, f"调用支付宝失败：{e}")

    return ok(res)


@bp.delete("/notify-logs")
def clear_logs():
    clear_notify_logs()
    return ok(None, "已清空")


# ---------- 评论管理 ----------
_COMMENT_MAX_LEN = 500
_COMMENT_MAX_IMAGES = 9
_DEFAULT_AVATAR = "linear-gradient(135deg,#dde6f0,#aab8c8)"


def _comment_admin_view(c: dict, product_name_by_id: dict) -> dict:
    ts = int(c.get("created_at") or 0)
    out = dict(c)
    out["time"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
    )
    out["product_name"] = product_name_by_id.get(c.get("product_id"), "")
    # 后台展示也用相对路径即可（管理后台和后端同域，<img src="/..."> 可直渲）
    raw_imgs = c.get("images") if isinstance(c.get("images"), list) else []
    out["images"] = [x for x in raw_imgs if isinstance(x, str) and x]
    return out


def _clean_comment_images(raw) -> list[str]:
    """与 routes/comments._clean_images 同语义：仅保留 / 或 http(s):// 开头的字符串、
    去重、截到 _COMMENT_MAX_IMAGES。
    """
    if not isinstance(raw, list):
        return []
    seen, out = set(), []
    for x in raw:
        if not isinstance(x, str):
            continue
        s = x.strip()
        if not s or s in seen:
            continue
        if not s.startswith(("/", "http://", "https://")):
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= _COMMENT_MAX_IMAGES:
            break
    return out


def _parse_admin_comment_time(raw) -> int | None:
    """admin 表单的"评论时间"输入：支持 datetime-local（YYYY-MM-DDTHH:MM[:SS]）/
    常规字符串 / 已经是 unix 秒的数字。返回 unix 秒，解析不出来返回 None。
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        v = int(raw)
        return v if v > 0 else None
    s = str(raw).strip().replace("T", " ").replace("/", "-")
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(time.mktime(time.strptime(s, fmt)))
        except ValueError:
            continue
    return None


@bp.get("/comments")
def list_comments_admin():
    """支持 ?product_id= 过滤；按时间倒序。"""
    pid = request.args.get("product_id", type=int)
    items = comment_repo.list(product_id=pid) if pid else comment_repo.list()
    items.sort(key=lambda x: -int(x.get("created_at") or 0))
    # 一次性把 product_name 拼上，省得前端反查
    name_map = {p["id"]: p.get("name", "") for p in product_repo.list()}
    return ok({
        "list": [_comment_admin_view(c, name_map) for c in items],
        "total": len(items),
    })


@bp.post("/comments")
def create_comment_admin():
    """后台手动新增评论：支持指定用户名、上传图片、自定义评论时间（用于补录历史好评）。"""
    body = request.get_json(silent=True) or {}

    try:
        pid = int(body.get("product_id") or 0)
    except (TypeError, ValueError):
        return fail(1, "product_id 非法")
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")

    content = (body.get("content") or "").strip()
    if not content:
        return fail(1, "评论内容不能为空")
    if len(content) > _COMMENT_MAX_LEN:
        return fail(1, f"评论内容过长（上限 {_COMMENT_MAX_LEN} 字）")

    try:
        stars = int(body.get("stars") or 5)
    except (TypeError, ValueError):
        stars = 5
    stars = max(1, min(5, stars))

    user = (body.get("user") or "").strip() or "匿名用户"
    avatar = (body.get("avatar_color") or "").strip() or _DEFAULT_AVATAR
    images = _clean_comment_images(body.get("images"))

    rec = comment_repo.create({
        "product_id": pid,
        "user_id": "",                # 后台手录无具体用户
        "user": user,
        "avatar_color": avatar,
        "stars": stars,
        "content": content,
        "images": images,
    })

    # 评论时间可被运营手动指定（如补录历史评价）；只改 payload.created_at，
    # 列表/详情接口排序与展示均读 payload 字段，足以生效。
    ts = _parse_admin_comment_time(body.get("created_at") or body.get("time"))
    if ts:
        rec = comment_repo.update(rec["id"], {"created_at": ts}) or rec

    name_map = {p["id"]: p.get("name", "") for p in product_repo.list()}
    return ok(_comment_admin_view(rec, name_map), "已新增评论")


@bp.delete("/comments/<int:cid>")
def delete_comment_admin(cid):
    if not comment_repo.delete(cid):
        return fail(404, "评论不存在")
    return ok(None, "已删除")


# ---------- 文件上传 ----------
# 上传根目录：static/products/uploads/，访问路径 /product/asset/products/uploads/<f>
_UPLOAD_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "static", "products", "uploads")
)
_UPLOAD_PUBLIC_PREFIX = "/product/asset/products/uploads"
_ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
_MAX_BYTES = 8 * 1024 * 1024  # 8MB


@bp.post("/upload")
def upload():
    """通用图片上传：multipart/form-data，字段名 file；返回 { url, name, size }。

    URL 形如 /product/asset/products/uploads/<uuid>.<ext>，由 landing.py 的
    `/product/asset/<path>` 静态映射对外提供。
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return fail(1, "请选择文件")

    raw_name = f.filename
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
    if ext not in _ALLOWED_EXTS:
        return fail(1, f"不支持的格式：.{ext or '?'}（仅允许 {', '.join(sorted(_ALLOWED_EXTS))}）")

    # 读到内存做大小校验（图片不会太大）
    blob = f.read()
    if len(blob) > _MAX_BYTES:
        return fail(1, f"文件过大：{len(blob)//1024//1024}MB（上限 {_MAX_BYTES//1024//1024}MB）")
    if not blob:
        return fail(1, "空文件")

    os.makedirs(_UPLOAD_DIR, exist_ok=True)
    fname = f"{int(time.time())}_{uuid.uuid4().hex[:10]}.{ext}"
    fpath = os.path.join(_UPLOAD_DIR, fname)
    with open(fpath, "wb") as out:
        out.write(blob)

    return ok({
        "url": f"{_UPLOAD_PUBLIC_PREFIX}/{fname}",
        "name": raw_name,
        "size": len(blob),
    }, "上传成功")


@bp.post("/products/<int:pid>/qrcode")
def product_qrcode(pid):
    """生成指向该商品小程序详情页的小程序码（运营分享用）。

    body: { days?: int }  —— 传了就把租期带进 query，扫码后小程序自动选中该租期
    返回: { qr_code_url, page, query }

    实现迭代历史：
      v1: alipay.open.app.qrcode.create 标准用法（url_param + query_param 分开）
          → 支付宝扫码后 query 投递行为黑盒（有的版本塞 q.query，有的塞 q.scene），
            小程序端兼容多种 wrapper 才能不丢参数；运营反馈"商品参数缺失"。
      v2: 本地 qrcode 库 + alipays://platformapi/startapp 自构 deep-link
          → 支付宝扫一扫对生 alipays:// QR 处理不稳定，依然"商品参数缺失"。
      v3（当前）: 仍走 alipay.open.app.qrcode.create，但 **把 query 内联进 url_param**
          → url_param = "pages/product/product?id=9&days=7", query_param = ""
          → 支付宝识别为完整启动 URL，参数按标准 query 解析后直传给 onLoad(q)，
            落到 q.id / q.days；与小程序原生 my.navigateTo 跳转行为完全一致，
            小程序端只看 q.id 即可，无需任何 wrapper 解析。
    """
    p = product_repo.get(pid)
    if not p:
        return fail(404, "商品不存在")

    body = request.get_json(silent=True) or {}
    days = body.get("days")
    try:
        days = int(days) if days not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        days = 0
    if days < 0:
        days = 0

    page = "pages/product/product"
    query = f"id={pid}" + (f"&days={days}" if days > 0 else "")
    # 双重保险：
    #   url_param   把 query 内联（让支付宝按标准 URL 解析时 q.id 直接落到 onLoad）
    #   query_param 同样给真实 query（满足官方接口非空校验；即使支付宝按"传统模式"
    #               把整串塞到 q.query，小程序端 _normalizeQuery 也能解析）
    url_param = f"{page}?{query}"
    describe = (p.get("name") or "商品") + (f" {days}天" if days > 0 else "")

    # 缓存命中：同一 (商品, 租期) 的小程序码只生成一次。
    # alipay.open.app.qrcode.create 对"相同参数的重复请求"有频控——不缓存的话，
    # 反复打开同一商品自动生成默认码（参数恒为 id=pid）极易被限流而"忽好忽坏"。
    cache = p.get("qr_cache")
    cache = cache if isinstance(cache, dict) else {}
    cache_key = str(days)
    if cache.get(cache_key):
        return ok({
            "qr_code_url": cache[cache_key],
            "page": page, "query": query, "url_param": url_param,
            "cached": True,
        }, "已生成")

    from app.alipay_client import get_client
    try:
        qr_url = get_client().create_app_qrcode(
            url_param=url_param,
            query_param=query,
            describe=describe[:30],
        )
    except Exception as e:
        return fail(1, f"生成小程序码失败：{e}")

    # 写入缓存（失败不阻断返回）
    try:
        new_cache = dict(cache)
        new_cache[cache_key] = qr_url
        product_repo.update(pid, {"qr_cache": new_cache})
    except Exception:
        pass

    return ok({
        "qr_code_url": qr_url,
        "page":        page,
        "query":       query,
        "url_param":   url_param,   # 排查用：实际传给 alipay 的完整路径
    }, "已生成")


@bp.put("/users/<uid>")
def update_user(uid):
    body = request.get_json(silent=True) or {}
    if not user_repo.get(uid):
        return fail(404, "用户不存在")
    patch = {k: body[k] for k in
             ("nickname", "phone", "real_name", "id_card", "verified") if k in body}
    updated = user_repo.update(uid, patch)
    return ok(updated, "更新成功")


@bp.get("/users/<uid>/addresses")
def user_addresses(uid):
    """用户的收货地址列表（用户管理编辑弹窗展示用，默认地址排前）。"""
    if not user_repo.get(uid):
        return fail(404, "用户不存在")
    items = address_repo.list(user_id=uid)
    items.sort(key=lambda a: (0 if a.get("is_default") else 1, -int(a.get("created_at") or 0)))
    out = []
    for a in items:
        out.append({
            "id": a.get("id"),
            "receiver_name": a.get("receiver_name") or "",
            "receiver_phone": a.get("receiver_phone") or "",
            "full": f"{a.get('province','')} {a.get('city','')} {a.get('district','')} {a.get('detail','')}".strip(),
            "is_default": bool(a.get("is_default")),
        })
    return ok({"list": out, "total": len(out)})


# ============ 工作人员（staff）CRUD ============

@bp.get("/staffs")
def list_staffs():
    items = [_safe_staff(s) for s in staff_repo.list()]
    return ok({"list": items, "total": len(items)})


@bp.get("/staffs/<int:sid>")
def get_staff(sid):
    s = staff_repo.get(sid)
    if not s:
        return fail(404, "工作人员不存在")
    return ok(_safe_staff(s))


@bp.post("/staffs")
def create_staff():
    if g.staff.get("role") != "admin":
        return fail(403, "仅 admin 可创建工作人员")
    body = request.get_json(silent=True) or {}
    username  = (body.get("username") or "").strip()
    real_name = (body.get("real_name") or "").strip()
    password  = body.get("password") or ""
    role      = body.get("role") if body.get("role") in ("admin", "operator") else "operator"

    if not username:
        return fail(1, "用户名必填")
    if staff_repo.find(username=username):
        return fail(1, "用户名已存在")
    try:
        pw_hash = hash_password(password)
    except ValueError as e:
        return fail(1, str(e))

    rec = staff_repo.create({
        "username": username, "real_name": real_name,
        "password_hash": pw_hash, "role": role,
    })
    return ok(_safe_staff(rec), "已添加")


@bp.put("/staffs/<int:sid>")
def update_staff(sid):
    s = staff_repo.get(sid)
    if not s:
        return fail(404, "工作人员不存在")
    if g.staff.get("role") != "admin" and g.staff["id"] != sid:
        return fail(403, "无权修改他人")
    body = request.get_json(silent=True) or {}
    patch = {}
    for k in ("real_name", "role"):
        if k in body:
            patch[k] = body[k]
    # 非 admin 不允许改 role
    if g.staff.get("role") != "admin":
        patch.pop("role", None)
        body.pop("role", None)
    updated = staff_repo.update(sid, patch)
    return ok(_safe_staff(updated), "已更新")


@bp.delete("/staffs/<int:sid>")
def delete_staff(sid):
    if g.staff.get("role") != "admin":
        return fail(403, "仅 admin 可删除")
    if sid == g.staff["id"]:
        return fail(1, "不能删除自己")
    if not staff_repo.get(sid):
        return fail(404, "工作人员不存在")
    staff_repo.delete(sid)
    auth_token.revoke_all_for_staff(sid)
    return ok(None, "已删除")


@bp.post("/staffs/<int:sid>/password")
def change_password(sid):
    """改密：本人需提供 old_password；admin 改他人可省略 old_password。"""
    s = staff_repo.get(sid)
    if not s:
        return fail(404, "工作人员不存在")
    body = request.get_json(silent=True) or {}
    new_pw = body.get("new_password") or ""
    old_pw = body.get("old_password") or ""

    is_self  = sid == g.staff["id"]
    is_admin = g.staff.get("role") == "admin"
    if not is_self and not is_admin:
        return fail(403, "无权改他人密码")
    if is_self and not verify_password(old_pw, s.get("password_hash", "")):
        return fail(1, "原密码错误")

    try:
        pw_hash = hash_password(new_pw)
    except ValueError as e:
        return fail(1, str(e))

    staff_repo.update(sid, {"password_hash": pw_hash})
    # 改密后注销该用户所有 token，强制重登
    auth_token.revoke_all_for_staff(sid)
    return ok(None, "密码已更新，请重新登录")


# ---------- 系统设置（settings.json）—— 仅 admin 角色可访问/修改 ----------
@bp.get("/settings")
def admin_get_settings():
    if g.staff.get("role") != "admin":
        return fail(403, "仅 admin 可查看系统设置")
    from app.settings import all_settings
    return ok(all_settings())


@bp.put("/settings")
def admin_update_settings():
    """部分更新；只接受 settings._DEFAULTS 里声明过的 key，未知字段会被丢弃。"""
    if g.staff.get("role") != "admin":
        return fail(403, "仅 admin 可修改系统设置")
    from app.settings import update as settings_update
    body = request.get_json(silent=True) or {}
    try:
        merged = settings_update(body)
    except ValueError as e:
        return fail(1, str(e))
    return ok(merged, "已保存")


# =========================== 预授权扣款（信用免押方案 A） =========================== #
# 接口：
#   POST /api/admin/orders/<oid>/charges       发起一笔扣款（alipay.trade.pay）
#   GET  /api/admin/orders/<oid>/charges       查这个订单全部扣款流水
#   POST /api/admin/charges/<out_trade_no>/query  刷新单笔扣款状态（alipay.trade.query）
#   POST /api/admin/charges/<out_trade_no>/close  取消未成功的扣款（alipay.trade.close）

_TRADE_STATUS_LABEL = {
    "INIT":            "已创建",
    "WAIT_BUYER_PAY":  "等待扣款",
    "TRADE_SUCCESS":   "扣款成功",
    "TRADE_CLOSED":    "已关闭",
    "TRADE_FINISHED":  "已完结（不可退）",
    "FAILED":          "失败",
}

# 扣款原因枚举：必须先选分类，才能写具体说明。
# 与支付宝协议中允许的扣款场景对齐（租金/逾期违约金/损坏赔偿/用户确认其他）。
_CHARGE_REASON_TYPES = {
    "RENT_SERVICE":         "租金/服务费",
    "OVERDUE_PENALTY":      "逾期违约金",
    "DAMAGE_LOSS":          "损坏/丢失赔偿",
    "USER_CONFIRMED_OTHER": "其他（用户确认）",
}


def _trade_view(t: dict) -> dict:
    """扣款流水的展示视图：补 status_label / reason_type_label / 时间字符串 + 退款字段加工。"""
    if not t:
        return t
    out = dict(t)
    out["status_label"] = _TRADE_STATUS_LABEL.get(t.get("status") or "", t.get("status") or "")
    out["reason_type_label"] = _CHARGE_REASON_TYPES.get(t.get("reason_type") or "", "")
    ts_created = int(t.get("created_at") or 0)
    out["created_at_text"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts_created)) if ts_created else ""
    )
    # 退款流水：每条加 created_at_text 给前端展示
    refunds_view = []
    for r in (t.get("refunds") or []):
        rv = dict(r)
        rts = int(r.get("created_at") or 0)
        rv["created_at_text"] = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rts)) if rts else ""
        )
        refunds_view.append(rv)
    out["refunds"] = refunds_view
    # 剩余可退金额（amount - refunded_amount），前端用来禁用按钮 / 限制输入
    try:
        refundable = float(t.get("amount") or 0) - float(t.get("refunded_amount") or 0)
    except (TypeError, ValueError):
        refundable = 0.0
    out["refundable_amount"] = round(max(0.0, refundable), 2)
    return out


def _is_refundable_status(s: str) -> bool:
    """支付宝端：只有支付成功的交易才能退款。"""
    return s in ("TRADE_SUCCESS", "TRADE_FINISHED")


# 哪些扣款实际消耗了 alipay 端的冻结池
# trade.refund 不会回填冻结池（alipay 设计），所以这里不去减退款
_CONSUMED_TRADE_STATUS = frozenset({"TRADE_SUCCESS", "TRADE_FINISHED"})


def _calc_unfreezable_amount(order: dict) -> float:
    """计算订单在 alipay 端的剩余可解冻金额。

    冻结池 = freeze_amount（下单时落库的快照；老数据回落 deposit_freeze）
    剩余可解冻 = 冻结池 - 已消耗（所有 TRADE_SUCCESS/FINISHED 扣款的 amount）

    注意：refund 不进入计算——它是商家→买家的钱流，不补回 alipay 冻结池。
    """
    base = float(order.get("freeze_amount") or 0)
    if base <= 0:
        # 历史订单可能没 freeze_amount，回落用 deposit_freeze
        base = float(order.get("deposit_freeze") or 0)
    consumed = 0.0
    try:
        for t in trade_repo.list(order_id=order.get("id")):
            if (t.get("status") or "") in _CONSUMED_TRADE_STATUS:
                try:
                    consumed += float(t.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
    except Exception:
        # trade 表查询出错时按"无消耗"处理，避免完全卡死解冻流程
        pass
    return round(max(0.0, base - consumed), 2)


@bp.get("/charges/reason-types")
def admin_charge_reason_types():
    """前端拉取扣款原因枚举，避免分类硬编码两份。"""
    return ok({
        "list": [{"value": k, "label": v} for k, v in _CHARGE_REASON_TYPES.items()],
    })


@bp.post("/orders/<oid>/charges")
def admin_create_charge(oid):
    """对一个订单发起一笔预授权扣款（信用免押 方案A 的核心入口）。

    Body:
      amount             必填，本次扣款金额
      reason_type        必填，扣款原因分类（_CHARGE_REASON_TYPES 中的枚举）
      reason_detail      选填，操作员填写的具体说明（自由文本）
      subject            选填，向后兼容字段；如未传 reason_type 时回退使用
      auth_confirm_mode  COMPLETE / NOT_COMPLETE（默认 NOT_COMPLETE）

    最终传给支付宝的 subject = "【分类label】具体说明"，便于用户在账单里直观看出扣款理由。
    reason_type / reason_detail 同时分开存储，便于后台筛选与统计。
    """
    from app.alipay_client import get_client
    o = order_repo.get(oid)
    if not o:
        return fail(404, "订单不存在")
    auth_no = (o.get("alipay_auth_no") or "").strip()
    if not auth_no:
        return fail(1, "订单缺少授权号 auth_no（用户尚未完成免押授权，无法发起扣款）")

    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get("amount") or 0)
    except Exception:
        return fail(1, "金额格式非法")
    if amount <= 0:
        return fail(1, "扣款金额必须大于 0")

    reason_type = (body.get("reason_type") or "").strip().upper()
    reason_detail = (body.get("reason_detail") or "").strip()
    if reason_type:
        if reason_type not in _CHARGE_REASON_TYPES:
            return fail(1, "reason_type 取值非法")
        type_label = _CHARGE_REASON_TYPES[reason_type]
        subject = f"【{type_label}】{reason_detail}" if reason_detail \
            else f"【{type_label}】{o.get('product_name') or '租赁'}"
    else:
        # 兼容旧调用方：未传 reason_type 时，退回到旧的 subject 透传逻辑
        subject = (body.get("subject") or "").strip() or f"{o.get('product_name') or '租赁'} 扣款"

    confirm_mode = (body.get("auth_confirm_mode") or "NOT_COMPLETE").upper()
    if confirm_mode not in ("COMPLETE", "NOT_COMPLETE"):
        return fail(1, "auth_confirm_mode 取值非法")

    # COMPLETE = 扣后自动解冻剩余冻结金额（损坏赔偿/最后一笔结算场景）
    # 必须确认用户已经寄回设备：
    #   - 订单状态必须是 return_inspecting（用户已提交寄回快递）
    #   - return_logistics_no 必填（前一步会自动落库，这里再兜一层防绕过）
    # 防止商家在用户还没寄回的情况下就先扣完款 + 解冻押金。
    if confirm_mode == "COMPLETE":
        cur_status = o.get("status") or ""
        if cur_status != "return_inspecting":
            cur_label = _ORDER_STATUS_LABEL.get(cur_status, cur_status)
            return fail(
                1,
                f"「扣后解冻剩余」仅在订单为「核验中」时可用（当前为「{cur_label}」）。"
                "请先确认用户已经提交寄回快递。",
            )
        if not (o.get("return_logistics_no") or "").strip():
            return fail(1, "用户尚未提交退回物流单号，不能使用「扣后解冻剩余」")

    # 生成商户扣款号：oid + 时间戳 + 4 位随机；64 字符内
    out_trade_no = f"P{oid}{int(time.time())}{uuid.uuid4().hex[:4].upper()}"

    now = int(time.time())
    trade_repo.create({
        "id":                out_trade_no,
        "order_id":          oid,
        "amount":            amount,
        "subject":           subject,
        "reason_type":       reason_type,
        "reason_detail":     reason_detail,
        "auth_no":           auth_no,
        "auth_confirm_mode": confirm_mode,
        "status":            "INIT",
        "operator":          (g.staff.get("username") or "") if hasattr(g, "staff") and g.staff else "",
    })

    # 账单详情页服务卡片需要的商品上下文：商品名 + 主图绝对 URL
    # 主图取该商品的 covers[0]（已被 admin 上传到 static/products/uploads/）→ 拼绝对 URL
    product_name_for_card = o.get("product_name") or ""
    product_image_url = ""
    if o.get("product_id"):
        _p = product_repo.get(o["product_id"]) or {}
        covers = _p.get("covers") if isinstance(_p.get("covers"), list) else []
        first_cover = (covers[0] if covers else "") or (_p.get("cover_url") or "")
        if first_cover:
            if first_cover.startswith(("http://", "https://")):
                product_image_url = first_cover
            elif first_cover.startswith("/"):
                product_image_url = AlipayConfig.notify_base() + first_cover
        if not product_name_for_card:
            product_name_for_card = _p.get("name") or ""

    try:
        resp = get_client().auth_trade_pay(
            out_trade_no=out_trade_no,
            total_amount=amount,
            subject=subject,
            auth_no=auth_no,
            auth_confirm_mode=confirm_mode,
            # ── 服务卡片上下文（账单详情页渲染）──
            order_id=oid,
            product_id=o.get("product_id") or None,
            product_name=product_name_for_card or None,
            product_image_url=product_image_url or None,
            body=reason_detail or None,
            service_id=AlipayConfig.SERVICE_ID or None,
        )
    except Exception as e:
        trade_repo.update(out_trade_no, {
            "status":   "FAILED",
            "fail_msg": str(e)[:500],
        })
        return fail(1, f"调用支付宝失败：{e}")

    # 解析同步响应。预授权扣款的 sync 响应码有"误导性"：
    # 即使返回 code=40004 等错误码，alipay 端也可能已经把 trade 落到
    # WAIT_BUYER_PAY 等用户主动支付。所以 sync 拿不到明确结论时，立刻
    # 调一次 trade.query 兜底，让运营第一时间看到真实状态。
    code = str(resp.get("code") or "")
    sync_trade_status = (resp.get("trade_status") or "").strip().upper()
    patch: dict = {"raw_pay": resp}

    def _absorb(src: dict) -> None:
        """把响应里的 trade_no / buyer_logon_id / gmt_payment / receipt_amount 抽到 patch。"""
        if src.get("trade_no"):       patch["trade_no"]       = src["trade_no"]
        if src.get("buyer_logon_id"): patch["buyer_logon_id"] = src["buyer_logon_id"]
        if src.get("gmt_payment"):    patch["gmt_payment"]    = src["gmt_payment"]
        if src.get("receipt_amount") is not None:
            try: patch["receipt_amount"] = float(src["receipt_amount"])
            except (TypeError, ValueError): pass

    resolved_status: str | None = None
    if code == "10000":
        # alipay 受理；trade_status 才是真实状态，缺失时回落到 TRADE_SUCCESS
        resolved_status = sync_trade_status or "TRADE_SUCCESS"
        _absorb(resp)
    elif code == "10003":
        # 业务处理中
        resolved_status = "WAIT_BUYER_PAY"
        _absorb(resp)
    else:
        # sync 报错 → 立即 query 兜底
        try:
            q_resp = get_client().trade_query(out_trade_no=out_trade_no)
            patch["raw_query"] = q_resp
            q_code = str(q_resp.get("code") or "")
            if q_code == "10000":
                q_status = (q_resp.get("trade_status") or "").strip().upper()
                if q_status:
                    resolved_status = q_status
                    _absorb(q_resp)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "auto-query after create_charge failed oid=%s out_trade_no=%s err=%s",
                oid, out_trade_no, e,
            )

    # 根据解析后的状态落库
    if resolved_status == "TRADE_SUCCESS":
        patch.update({"status": "TRADE_SUCCESS", "paid_at": now})
    elif resolved_status == "WAIT_BUYER_PAY":
        patch["status"] = "WAIT_BUYER_PAY"
    elif resolved_status in ("TRADE_CLOSED", "TRADE_FINISHED"):
        patch["status"] = resolved_status
        if resolved_status == "TRADE_FINISHED":
            patch["paid_at"] = patch.get("paid_at") or now
    elif resolved_status:
        # 极少见的其他 trade_status，原样落库给运营排查（如 UNKNOWN）
        patch["status"] = resolved_status
    else:
        # sync 报错 + query 也找不到 trade → 真失败
        patch.update({
            "status":    "FAILED",
            "fail_code": resp.get("sub_code") or code,
            "fail_msg":  resp.get("sub_msg") or resp.get("msg") or "",
        })

    trade_repo.update(out_trade_no, patch)

    # 终态推断后再决定是否同步支付宝订单中心。TRADE_SUCCESS / TRADE_FINISHED
    # 才推（金额/状态有变化）；WAIT_BUYER_PAY 还没收到钱，没必要推。
    # COMPLETE 模式下，剩余冻结金额会被支付宝异步解冻，notify_auth_unfreeze
    # 回来后 transition_unfreeze_done 还会再 sync 一次（→ FINISHED），幂等。
    if resolved_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        try:
            from app import order_sync
            order_sync.sync_order(oid, reason=f"charge_{confirm_mode.lower()}")
        except Exception:
            # 同步失败不回滚扣款；sync_err 已写订单，运营可在"重新同步"按钮重试
            pass

    # COMPLETE 模式 = "扣完即解冻剩余"语义：alipay 同步返回 TRADE_SUCCESS/FINISHED 即
    # 等价于"剩余冻结金额已发起自动解冻"。此时不应再傻等 notify_auth_unfreeze 才推
    # 终态，否则一旦 notify 丢失/notify_url 不通，订单永远卡在「核验中」。
    # 设计原则：决定性同步操作直接同步推进；notify 作为兜底（幂等 transition 保护重复触发）。
    if (confirm_mode == "COMPLETE"
            and resolved_status in ("TRADE_SUCCESS", "TRADE_FINISHED")
            and o.get("status") in ("using", "return", "overdue", "return_inspecting")):
        try:
            from app.routes.orders import transition_unfreeze_done
            transition_unfreeze_done(oid)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                "complete-charge auto-finish failed oid=%s err=%s", oid, e,
            )

    updated = trade_repo.get(out_trade_no)
    # UI 提示按真实状态分级
    if resolved_status == "TRADE_SUCCESS" or resolved_status == "TRADE_FINISHED":
        msg = "扣款成功，订单已完成" if confirm_mode == "COMPLETE" else "扣款成功"
    elif resolved_status == "WAIT_BUYER_PAY":
        msg = "扣款已下发，待用户在支付宝端补充支付"
    elif resolved_status:
        msg = f"扣款已下发，当前状态：{resolved_status}"
    else:
        msg = f"扣款失败 {resp.get('sub_code') or code}"
    return ok(_trade_view(updated), msg)


@bp.get("/orders/<oid>/charges")
def admin_list_charges(oid):
    """订单的所有扣款流水，按时间倒序。"""
    items = trade_repo.list(order_id=oid)
    items.sort(key=lambda x: -int(x.get("created_at") or 0))
    return ok({
        "list":  [_trade_view(t) for t in items],
        "total": len(items),
    })


@bp.post("/charges/<out_trade_no>/query")
def admin_query_charge(out_trade_no):
    """刷新单笔扣款的状态（alipay.trade.query）。"""
    from app.alipay_client import get_client
    t = trade_repo.get(out_trade_no)
    if not t:
        return fail(404, "扣款记录不存在")
    try:
        resp = get_client().trade_query(out_trade_no=out_trade_no)
    except Exception as e:
        return fail(1, f"调用支付宝失败：{e}")

    code = str(resp.get("code") or "")
    patch: dict = {"raw_query": resp}
    if code == "10000":
        # 阿里返回的 trade_status 比本地状态更权威
        new_status = (resp.get("trade_status") or "").strip()
        if new_status:
            patch["status"] = new_status
        if resp.get("trade_no"):       patch["trade_no"]       = resp["trade_no"]
        if resp.get("buyer_logon_id"): patch["buyer_logon_id"] = resp["buyer_logon_id"]
        if resp.get("send_pay_date"):  patch["gmt_payment"]    = resp["send_pay_date"]
        if resp.get("receipt_amount"): patch["receipt_amount"] = float(resp["receipt_amount"])
    else:
        patch["fail_code"] = resp.get("sub_code") or code
        patch["fail_msg"]  = resp.get("sub_msg") or resp.get("msg") or ""
    trade_repo.update(out_trade_no, patch)
    return ok(_trade_view(trade_repo.get(out_trade_no)), "已刷新")


@bp.post("/charges/<out_trade_no>/close")
def admin_close_charge(out_trade_no):
    """取消未成功的扣款（alipay.trade.close）。仅 INIT / WAIT_BUYER_PAY 状态可关。"""
    from app.alipay_client import get_client
    t = trade_repo.get(out_trade_no)
    if not t:
        return fail(404, "扣款记录不存在")
    if t.get("status") not in ("INIT", "WAIT_BUYER_PAY"):
        return fail(1, f"当前状态 {t.get('status')}，仅未支付状态可关闭。已成功的扣款请走退款流程")

    op = (g.staff.get("username") or "admin") if hasattr(g, "staff") and g.staff else "admin"
    try:
        resp = get_client().trade_close(out_trade_no=out_trade_no, operator_id=op[:28])
    except Exception as e:
        return fail(1, f"调用支付宝失败：{e}")

    code = str(resp.get("code") or "")
    patch: dict = {"raw_close": resp}
    if code == "10000":
        patch.update({
            "status":    "TRADE_CLOSED",
            "closed_by": "admin",
            "closed_at": int(time.time()),
        })
    else:
        patch["fail_code"] = resp.get("sub_code") or code
        patch["fail_msg"]  = resp.get("sub_msg") or resp.get("msg") or ""
    trade_repo.update(out_trade_no, patch)
    return ok(_trade_view(trade_repo.get(out_trade_no)), "已关闭" if code == "10000" else f"关闭失败 {code}")


# ---------- 退款（alipay.trade.refund + alipay.trade.fastpay.refund.query） ----------
@bp.post("/charges/<out_trade_no>/refund")
def admin_refund_charge(out_trade_no):
    """对一笔扣款发起退款。支持多次部分退款；每次生成独立的 out_request_no。

    Body:
      amount  必填，本次退款金额（≤ amount - refunded_amount）
      reason  选填，退款理由（展示在用户支付宝账单详情里）
    """
    from app.alipay_client import get_client
    t = trade_repo.get(out_trade_no)
    if not t:
        return fail(404, "扣款记录不存在")
    if not _is_refundable_status(t.get("status") or ""):
        return fail(1, f"当前状态 {t.get('status')} 不可退款，仅 TRADE_SUCCESS / TRADE_FINISHED 可退")

    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get("amount") or 0)
    except Exception:
        return fail(1, "金额格式非法")
    if amount <= 0:
        return fail(1, "退款金额必须大于 0")

    paid     = float(t.get("amount") or 0)
    refunded = float(t.get("refunded_amount") or 0)
    refundable = round(paid - refunded, 2)
    if amount > refundable + 1e-9:
        return fail(1, f"退款金额 ¥{amount:.2f} 超出剩余可退 ¥{refundable:.2f}")

    reason = (body.get("reason") or "").strip()
    # 每笔退款独立的请求号；写库后调阿里。重试同一笔退款时务必复用相同号。
    out_request_no = "RF" + uuid.uuid4().hex[:16].upper()
    operator = (g.staff.get("username") or "admin") if hasattr(g, "staff") and g.staff else "admin"
    now = int(time.time())

    # 先记一条 INIT 占位，避免阿里端 raw 返回还在路上时本地完全没痕迹
    refunds = list(t.get("refunds") or [])
    refunds.append({
        "out_request_no": out_request_no,
        "amount":         round(amount, 2),
        "reason":         reason,
        "status":         "INIT",
        "fund_change":    "",
        "operator":       operator,
        "created_at":     now,
        "refund_at":      None,
        "raw_refund":     {},
        "raw_query":      {},
        "fail_code":      "",
        "fail_msg":       "",
    })
    trade_repo.update(out_trade_no, {"refunds": refunds})

    try:
        resp = get_client().trade_refund(
            refund_amount=amount,
            out_trade_no=out_trade_no,
            out_request_no=out_request_no,
            refund_reason=reason or None,
        )
    except Exception as e:
        # 同步异常：状态置 FAILED，但保留 out_request_no（重试用同一个）
        _patch_refund(out_trade_no, out_request_no, {
            "status":   "FAILED",
            "fail_msg": str(e)[:500],
        })
        return fail(1, f"调用支付宝失败：{e}")

    code = str(resp.get("code") or "")
    fund_change = (resp.get("fund_change") or "").upper()
    patch = {"raw_refund": resp}
    if code == "10000" and fund_change == "Y":
        patch.update({
            "status":      "REFUND_SUCCESS",
            "fund_change": "Y",
            "refund_at":   now,
        })
    elif code == "10000":
        # 请求受理但未确认资金变化，建议走 query 兜底
        patch.update({
            "status":      "SUBMITTED",
            "fund_change": fund_change,
        })
    else:
        patch.update({
            "status":    "FAILED",
            "fail_code": resp.get("sub_code") or code,
            "fail_msg":  resp.get("sub_msg") or resp.get("msg") or "",
        })
    _patch_refund(out_trade_no, out_request_no, patch)
    _recompute_refunded_amount(out_trade_no)
    return ok(_trade_view(trade_repo.get(out_trade_no)),
              "退款已成功" if patch.get("status") == "REFUND_SUCCESS"
              else (f"退款已受理，请稍后刷新 ({code})" if code == "10000"
                    else f"退款失败 {code}"))


@bp.post("/charges/<out_trade_no>/refund/query")
def admin_query_refund(out_trade_no):
    """刷新单笔退款的状态（alipay.trade.fastpay.refund.query）。

    Body:
      out_request_no  必填，要查的退款请求号
    """
    from app.alipay_client import get_client
    t = trade_repo.get(out_trade_no)
    if not t:
        return fail(404, "扣款记录不存在")
    body = request.get_json(silent=True) or {}
    out_request_no = (body.get("out_request_no") or "").strip()
    if not out_request_no:
        return fail(1, "缺少 out_request_no")

    try:
        resp = get_client().trade_refund_query(
            out_request_no=out_request_no,
            out_trade_no=out_trade_no,
        )
    except Exception as e:
        return fail(1, f"调用支付宝失败：{e}")

    code = str(resp.get("code") or "")
    patch = {"raw_query": resp}
    if code == "10000":
        refund_status = (resp.get("refund_status") or "").strip()
        if refund_status == "REFUND_SUCCESS":
            patch["status"]      = "REFUND_SUCCESS"
            patch["fund_change"] = "Y"
            if not (t.get("refunds") or [{}])[0].get("refund_at"):
                patch["refund_at"] = int(time.time())
        # 未返回 refund_status 表示尚未成功，状态不变
    else:
        patch["fail_code"] = resp.get("sub_code") or code
        patch["fail_msg"]  = resp.get("sub_msg") or resp.get("msg") or ""
    _patch_refund(out_trade_no, out_request_no, patch)
    _recompute_refunded_amount(out_trade_no)
    return ok(_trade_view(trade_repo.get(out_trade_no)), "已刷新退款状态")


def _patch_refund(out_trade_no: str, out_request_no: str, patch: dict) -> None:
    """局部更新 trade_repo.refunds 里某一条退款记录。"""
    t = trade_repo.get(out_trade_no)
    if not t:
        return
    refunds = list(t.get("refunds") or [])
    for i, r in enumerate(refunds):
        if r.get("out_request_no") == out_request_no:
            merged = {**r, **patch}
            refunds[i] = merged
            break
    trade_repo.update(out_trade_no, {"refunds": refunds})


def _recompute_refunded_amount(out_trade_no: str) -> None:
    """根据 refunds 列表里成功的退款重算累计已退款金额。"""
    t = trade_repo.get(out_trade_no)
    if not t:
        return
    total = 0.0
    for r in (t.get("refunds") or []):
        if r.get("status") == "REFUND_SUCCESS":
            try:
                total += float(r.get("amount") or 0)
            except (TypeError, ValueError):
                pass
    trade_repo.update(out_trade_no, {"refunded_amount": round(total, 2)})


# ---------- 用户退款申请审核（PENDING → APPROVED / REJECTED） ----------

_REFUND_APPLY_STATUS_LABEL = {
    "PENDING":  "待审核",
    "APPROVED": "已通过",
    "REJECTED": "已驳回",
}


def _refund_apply_row(t: dict) -> dict:
    """把一条 trade 拼成"退款申请"列表项，附带订单 / 用户上下文。"""
    ap = t.get("refund_apply") or {}
    oid = t.get("order_id") or ""
    o = order_repo.get(oid) if oid else None
    uid = (o or {}).get("user_id") or 0
    u = user_repo.get(uid) if uid else None

    applied = int(ap.get("applied_at") or 0)
    reviewed = int(ap.get("reviewed_at") or 0)
    paid_amt = float(t.get("amount") or 0)
    refunded = float(t.get("refunded_amount") or 0)

    return {
        # 这条申请的关键定位字段
        "out_trade_no":     t.get("id"),
        "order_id":         oid,
        # 退款申请状态
        "status":           ap.get("status") or "",
        "status_label":     _REFUND_APPLY_STATUS_LABEL.get(ap.get("status") or "", ""),
        "reason":           ap.get("reason") or "",
        "applied_at":       applied,
        "applied_at_text":  (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(applied))
                             if applied else ""),
        "reviewed_at":      reviewed,
        "reviewed_at_text": (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(reviewed))
                             if reviewed else ""),
        "reviewer":         ap.get("reviewer") or "",
        "rejected_reason":  ap.get("rejected_reason") or "",
        "apply_amount":     float(ap.get("apply_amount") or 0),
        "refund_out_request_no": ap.get("refund_out_request_no") or "",
        # 扣款本身的关键信息
        "amount":           round(paid_amt, 2),
        "refunded_amount":  round(refunded, 2),
        "refundable_amount": round(max(0.0, paid_amt - refunded), 2),
        "subject":          t.get("subject") or "",
        "reason_type":      t.get("reason_type") or "",
        "reason_type_label": _CHARGE_REASON_TYPES.get(t.get("reason_type") or "", ""),
        "reason_detail":    t.get("reason_detail") or "",
        "trade_status":     t.get("status") or "",
        # 订单上下文（让运营不用再点进订单详情就能判断）
        "order_status":     (o or {}).get("status") or "",
        "order_status_label": _ORDER_STATUS_LABEL.get(
            (o or {}).get("status") or "", (o or {}).get("status") or ""),
        "product_name":     (o or {}).get("product_name") or "",
        # 用户脱敏信息
        "user_id":          uid,
        "user_nickname":    (u or {}).get("nickname") or "",
        "user_phone":       (u or {}).get("phone") or "",
    }


@bp.get("/refunds")
def admin_list_refund_applies():
    """列出退款申请。

    Query:
      status  pending / approved / rejected / all（默认 pending）
    """
    status = (request.args.get("status") or "pending").strip().lower()
    want = {
        "pending":  {"PENDING"},
        "approved": {"APPROVED"},
        "rejected": {"REJECTED"},
        "all":      {"PENDING", "APPROVED", "REJECTED"},
    }.get(status, {"PENDING"})

    rows = []
    for t in trade_repo.list():
        ap = t.get("refund_apply") or {}
        s = ap.get("status") or ""
        if s in want:
            rows.append(_refund_apply_row(t))
    # 待审核按"申请时间正序"排（先到先处理）；其它按倒序看历史
    if want == {"PENDING"}:
        rows.sort(key=lambda r: r.get("applied_at") or 0)
    else:
        rows.sort(key=lambda r: -(r.get("reviewed_at") or r.get("applied_at") or 0))
    return ok({
        "list":  rows,
        "total": len(rows),
        # 顶部小徽标用：当前各 bucket 数量
        "counts": {
            "pending":  sum(1 for t in trade_repo.list()
                            if (t.get("refund_apply") or {}).get("status") == "PENDING"),
            "approved": sum(1 for t in trade_repo.list()
                            if (t.get("refund_apply") or {}).get("status") == "APPROVED"),
            "rejected": sum(1 for t in trade_repo.list()
                            if (t.get("refund_apply") or {}).get("status") == "REJECTED"),
        },
    })


@bp.post("/charges/<out_trade_no>/refund/approve")
def admin_approve_refund_apply(out_trade_no):
    """通过用户的退款申请：发起 alipay.trade.refund 实际退款，并把申请状态置 APPROVED。

    Body:
      amount  选填，本次退款金额（默认按"剩余可退"全额退；不能超出剩余可退）
    """
    from app.alipay_client import get_client
    t = trade_repo.get(out_trade_no)
    if not t:
        return fail(404, "扣款记录不存在")
    ap = t.get("refund_apply") or {}
    if ap.get("status") != "PENDING":
        return fail(1, f"当前申请状态 {ap.get('status') or '无'}，仅 PENDING 可审核通过")
    if not _is_refundable_status(t.get("status") or ""):
        return fail(1, f"扣款状态 {t.get('status')} 不可退款")

    paid     = float(t.get("amount") or 0)
    refunded = float(t.get("refunded_amount") or 0)
    refundable = round(paid - refunded, 2)
    if refundable <= 0:
        return fail(1, "该扣款已无剩余可退金额")

    body = request.get_json(silent=True) or {}
    try:
        amount = float(body.get("amount")) if body.get("amount") is not None else refundable
    except Exception:
        return fail(1, "金额格式非法")
    if amount <= 0:
        return fail(1, "退款金额必须大于 0")
    if amount > refundable + 1e-9:
        return fail(1, f"退款金额 ¥{amount:.2f} 超出剩余可退 ¥{refundable:.2f}")

    reason = ap.get("reason") or "用户申请退款"
    out_request_no = "RF" + uuid.uuid4().hex[:16].upper()
    operator = (g.staff.get("username") or "admin") if hasattr(g, "staff") and g.staff else "admin"
    now = int(time.time())

    # 先在 refunds 里占位一条 INIT；和 admin_refund_charge 走完全一致的两段提交
    refunds = list(t.get("refunds") or [])
    refunds.append({
        "out_request_no": out_request_no,
        "amount":         round(amount, 2),
        "reason":         reason,
        "status":         "INIT",
        "fund_change":    "",
        "operator":       operator,
        "created_at":     now,
        "refund_at":      None,
        "raw_refund":     {},
        "raw_query":      {},
        "fail_code":      "",
        "fail_msg":       "",
    })
    trade_repo.update(out_trade_no, {"refunds": refunds})

    try:
        resp = get_client().trade_refund(
            refund_amount=amount,
            out_trade_no=out_trade_no,
            out_request_no=out_request_no,
            refund_reason=reason or None,
        )
    except Exception as e:
        _patch_refund(out_trade_no, out_request_no, {
            "status":   "FAILED",
            "fail_msg": str(e)[:500],
        })
        return fail(1, f"调用支付宝失败：{e}")

    code = str(resp.get("code") or "")
    fund_change = (resp.get("fund_change") or "").upper()
    patch = {"raw_refund": resp}
    if code == "10000" and fund_change == "Y":
        patch.update({
            "status":      "REFUND_SUCCESS",
            "fund_change": "Y",
            "refund_at":   now,
        })
    elif code == "10000":
        patch.update({"status": "SUBMITTED", "fund_change": fund_change})
    else:
        patch.update({
            "status":    "FAILED",
            "fail_code": resp.get("sub_code") or code,
            "fail_msg":  resp.get("sub_msg") or resp.get("msg") or "",
        })
    _patch_refund(out_trade_no, out_request_no, patch)
    _recompute_refunded_amount(out_trade_no)

    # 阿里成功受理（10000）就把申请置 APPROVED；非 10000 保持 PENDING，让运营修复后再审。
    if code == "10000":
        new_apply = {**ap,
                     "status":      "APPROVED",
                     "reviewed_at": now,
                     "reviewer":    operator,
                     "refund_out_request_no": out_request_no}
        trade_repo.update(out_trade_no, {"refund_apply": new_apply})

    msg = ("已审核通过，退款成功" if patch.get("status") == "REFUND_SUCCESS"
           else (f"已受理，退款待支付宝确认 ({code})" if code == "10000"
                 else f"退款失败 {code}：{resp.get('sub_msg') or ''}"))
    return ok(_trade_view(trade_repo.get(out_trade_no)), msg)


@bp.post("/charges/<out_trade_no>/refund/reject")
def admin_reject_refund_apply(out_trade_no):
    """驳回用户的退款申请。

    Body:
      reject_reason  必填，给用户的驳回理由（会展示在订单详情扣款列表）
    """
    t = trade_repo.get(out_trade_no)
    if not t:
        return fail(404, "扣款记录不存在")
    ap = t.get("refund_apply") or {}
    if ap.get("status") != "PENDING":
        return fail(1, f"当前申请状态 {ap.get('status') or '无'}，仅 PENDING 可驳回")

    body = request.get_json(silent=True) or {}
    reject_reason = (body.get("reject_reason") or "").strip()
    if len(reject_reason) < 5:
        return fail(1, "驳回理由至少 5 个字")
    if len(reject_reason) > 500:
        return fail(1, "驳回理由不超过 500 字")

    operator = (g.staff.get("username") or "admin") if hasattr(g, "staff") and g.staff else "admin"
    now = int(time.time())
    new_apply = {**ap,
                 "status":          "REJECTED",
                 "reviewed_at":     now,
                 "reviewer":        operator,
                 "rejected_reason": reject_reason}
    trade_repo.update(out_trade_no, {"refund_apply": new_apply})
    return ok(_refund_apply_row(trade_repo.get(out_trade_no)), "已驳回，用户可重新申请")
