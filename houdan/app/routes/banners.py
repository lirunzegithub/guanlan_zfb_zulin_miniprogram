"""首页 Banner（顶部轮播图）。

接口契约：
  GET /api/banners → { hero: {...}, heroes: [...] }

* hero    = 首张顶部 banner（兼容老前端单图字段）
* heroes  = 全量顶部 banner（按 slot 升序）→ 小程序首页 swiper 轮播

注：首页三宫格（免押认证 / 售后无忧 / 流程安全）是固定入口，
   小程序前端硬编码，不通过本接口配置。

URL 处理：image_url 若是相对路径（/...）会拼到 NOTIFY_BASE，
        让小程序 <image> 能直接吃到绝对地址（同 products._abs 思路）。
"""
from flask import Blueprint
from app.response import ok
from app.config import AlipayConfig
from app.storage.repos import banner_repo

bp = Blueprint("banners", __name__)


def _abs(url: str) -> str:
    """相对 URL → 绝对 URL（与 products._abs 同语义，避免循环 import 选了复制）。"""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return AlipayConfig.notify_base() + url
    return url


def _normalize(b: dict) -> dict:
    out = dict(b)
    out["image_url"] = _abs(out.get("image_url"))
    return out


@bp.get("")
def get_banners():
    hero_list = banner_repo.list(position="hero")
    hero_list.sort(key=lambda x: (x.get("slot", 0), x.get("id", 0)))
    heroes = [_normalize(b) for b in hero_list]
    return ok({
        "hero":   heroes[0] if heroes else {},  # 兼容老前端单图字段
        "heroes": heroes,
    })
