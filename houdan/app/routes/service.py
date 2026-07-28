"""客服接口（仅电话客服）+ 小程序公开配置端点"""
from flask import Blueprint
from app.response import ok
from app.config import AlipayConfig
from app.settings import all_settings, get as setting_get
from app.storage.repos import faq_repo

bp = Blueprint("service", __name__)


def _abs_url(url: str) -> str:
    """相对路径 → 绝对 URL（小程序 <image> 需要绝对地址）。"""
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://", "data:")):
        return url
    if url.startswith("/"):
        return AlipayConfig.notify_base() + url
    return url


SERVICE_BANNER = {
    "title": "客服中心",
    "sub": "租赁等问题，平台客服在线答疑",
    "brand": "观澜数码租赁",
}


@bp.get("/info")
def info():
    return ok({
        "banner": SERVICE_BANNER,
        "phone": setting_get("service_phone"),
        "online_enabled": False,
    })


@bp.get("/faqs")
def faqs():
    """常见问题列表：从 faq_repo 拉，按 sort 升序，再按 id 兜底。
    后台增删改后即时生效。
    """
    items = faq_repo.list()
    items.sort(key=lambda x: (int(x.get("sort") or 0), int(x.get("id") or 0)))
    # 只返回前端需要的字段，避免泄露内部时间戳等
    return ok([
        {"id": it.get("id"), "q": it.get("q") or "", "a": it.get("a") or ""}
        for it in items
    ])


# 小程序公开拉的运营配置（无需登录）。物流免租期等业务参数走这里。
@bp.get("/config")
def public_config():
    s = all_settings()
    return ok({
        "ship_free_days": int(s.get("ship_free_days") or 0),
        "service_phone":  s.get("service_phone") or "",
        # 是否允许日历手动点选起止日期（False = 只能用快捷预设）
        "allow_manual_date_pick": bool(s.get("allow_manual_date_pick", True)),
        # 冻结口径：True = 押金+租金一起冻，False = 只冻押金。
        # 确认订单页要在下单前把「预计冻结多少」说清楚，故需要这个开关。
        # 仅供展示；订单真正的冻结额在建单时落 freeze_amount 快照。
        "freeze_includes_rent": bool(s.get("freeze_includes_rent", True)),
        # 公司名称（小程序底部 / 后台侧栏底部展示）
        "company_name": s.get("company_name") or "",
        # 软件 LOGO（小程序"我的"头像 / 后台 favicon + 左上角），绝对 URL
        "logo_url": _abs_url(s.get("logo_url")),
    })
