"""商品评论：列表 + 创建 + 配图上传。

接口契约：
  GET  /api/comments?product_id=<pid>&page=1&size=20
       → { list: [...], total: N, page, size }
  POST /api/comments
       body: { product_id, stars, content, images?: [url...], avatar_color? }
       → 创建后的评论记录
  POST /api/comments/upload  (multipart/form-data, field name = file)
       → { url, name, size }

时间字段：存 created_at（int 秒级时间戳），列表里转成 "YYYY-MM-DD HH:MM:SS"
方便前端直接展示，不让前端再做格式化。

图片字段：images 存相对路径数组，列表 / 详情接口出参时 _abs 拼成绝对 URL，
让小程序 <image> 标签可以直接渲染。
"""
from __future__ import annotations

import os
import time
import uuid

from flask import Blueprint, request

from app.config import AlipayConfig
from app.response import ok, fail
from app.storage.repos import comment_repo, product_repo
from app.current_user import current_user, current_user_id

bp = Blueprint("comments", __name__)

_DEFAULT_AVATAR = "linear-gradient(135deg,#dde6f0,#aab8c8)"
_MAX_LEN = 500
_MAX_IMAGES = 9

# 上传目录：与 admin 上传共享 static/products/uploads，独立 comments/ 子目录
_UPLOAD_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "static", "products", "uploads", "comments")
)
_UPLOAD_PUBLIC_PREFIX = "/product/asset/products/uploads/comments"
_ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
_MAX_BYTES = 8 * 1024 * 1024  # 8MB


def _abs(url: str) -> str:
    """相对路径 → 绝对 URL（与 products._abs 同语义）。"""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return AlipayConfig.NOTIFY_BASE.rstrip("/") + url
    return url


def _to_view(c: dict) -> dict:
    """转换给前端展示的形态：补 time + images 绝对化。"""
    ts = int(c.get("created_at") or 0)
    out = dict(c)
    out["time"] = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else ""
    )
    raw_imgs = c.get("images") if isinstance(c.get("images"), list) else []
    out["images"] = [u for u in (_abs(x) for x in raw_imgs) if u]
    return out


def _clean_images(raw) -> list[str]:
    """落库前清洗：仅保留以 / 或 http(s):// 开头的字符串、去重、截到 _MAX_IMAGES 上限。"""
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
        if len(out) >= _MAX_IMAGES:
            break
    return out


@bp.get("")
def list_comments():
    pid = request.args.get("product_id", type=int)
    if not pid:
        return fail(1, "缺少 product_id")
    page = max(request.args.get("page", default=1, type=int), 1)
    size = min(request.args.get("size", default=20, type=int), 100)

    items = comment_repo.list(product_id=pid)
    items.sort(key=lambda x: -int(x.get("created_at") or 0))
    total = len(items)
    start = (page - 1) * size
    return ok({
        "list": [_to_view(c) for c in items[start:start + size]],
        "total": total,
        "page": page,
        "size": size,
    })


@bp.post("")
def create_comment():
    body = request.get_json(silent=True) or {}
    pid = body.get("product_id")
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return fail(1, "product_id 非法")
    if not product_repo.get(pid):
        return fail(404, "商品不存在")

    content = (body.get("content") or "").strip()
    if not content:
        return fail(1, "评论内容不能为空")
    if len(content) > _MAX_LEN:
        return fail(1, f"评论内容过长（上限 {_MAX_LEN} 字）")

    try:
        stars = int(body.get("stars") or 5)
    except (TypeError, ValueError):
        stars = 5
    stars = max(1, min(5, stars))

    images = _clean_images(body.get("images"))

    u = current_user()
    rec = comment_repo.create({
        "product_id": pid,
        "user_id": current_user_id(),
        "user": (u.get("nickname") or "").strip() or "匿名用户",
        "avatar_color": body.get("avatar_color") or _DEFAULT_AVATAR,
        "stars": stars,
        "content": content,
        "images": images,
    })
    return ok(_to_view(rec), "评论已发布")


@bp.post("/upload")
def upload_image():
    """用户侧图片上传（评价配图）。

    multipart/form-data，字段名 file；返回 { url, name, size }。
    URL 形如 /product/asset/products/uploads/comments/<uuid>.<ext>，
    由 landing 的 /product/asset/<path> 静态映射对外提供。

    需登录：路由不在 _AUTH_EXEMPT 白名单里，未带 token 会被全局守卫拦下。
    """
    f = request.files.get("file")
    if not f or not f.filename:
        return fail(1, "请选择文件")

    raw_name = f.filename
    ext = raw_name.rsplit(".", 1)[-1].lower() if "." in raw_name else ""
    if ext not in _ALLOWED_EXTS:
        return fail(1, f"不支持的格式：.{ext or '?'}（仅允许 {', '.join(sorted(_ALLOWED_EXTS))}）")

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
        "url":  f"{_UPLOAD_PUBLIC_PREFIX}/{fname}",
        "name": raw_name,
        "size": len(blob),
    }, "上传成功")
