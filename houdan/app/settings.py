"""运营可配置项（settings.json 持久化）。

设计原则：
- 只放"业务运营层面随时可能调"的字段；敏感凭据/域名仍保留在 config.py
- 读写都通过这里走，调用方不直接碰 JSON 文件
- 默认值在 _DEFAULTS 里；首次启动若文件不存在自动用默认值写一份
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any


_PATH = Path(__file__).resolve().parent.parent / "data" / "settings.json"
_lock = threading.Lock()

# 默认值。新增字段直接加在这里，旧 settings.json 不存在该 key 时自动回落到默认。
_DEFAULTS: dict[str, Any] = {
    # 公网 HTTPS 域名：支付宝异步通知/回调地址前缀 + 小程序图片绝对地址前缀都用它。
    # 必须是已备案、且已加入小程序「服务器域名 / downloadFile 合法域名」白名单的域名。
    # 空 = 回落到 config.py 的 NOTIFY_BASE 占位常量（图片不显示、回调打不到）。
    "notify_base":          "",
    "ship_free_days":       3,                   # 物流免租期（天）
    "service_phone":        "400-000-0000",      # 客服电话（部署后在管理后台「设置」里改成自己的）
    "alipay_app_id":        "",                  # 支付宝/小程序 APPID（管理后台「设置」里填）
    # 信用借还 SERVICE_ID：开放平台「信用服务管理」创建信用免押服务后拿到的服务 ID。
    # 空 = 支付宝识别不到信用借还业务，免押会降级为普通预授权（无免押按钮）。免押必配。
    "alipay_service_id":    "",
    # 信用借还业务类目（→ 免押 extra_param.category）：如 RENT_DIGITAL(数码其他) / RENT_PHONE(手机)。
    # 合法取值见官方「信用预授权类目」表 https://opendocs.alipay.com/open/10719
    # 有合理默认值，一般无需改；同时经营多类目租赁时才按需切换。
    "alipay_scene_code":    "RENT_DIGITAL",
    # 公司名称：小程序"我的"底部 + 后台侧栏底部展示，不再硬编码
    "company_name":         "示例数码租赁有限责任公司",
    # 软件 LOGO：后台浏览器标签页 favicon + 左上角品牌图标；小程序"我的"头像。
    # 存相对路径（/product/asset/products/uploads/<f>）或绝对 URL；空 = 用默认占位
    "logo_url":             "",
    # 冻结模式：True = 押金 + 总租金一起冻结（默认，保持历史行为）
    #          False = 仅冻结押金（租金到期再扣）
    # 注：只影响"新建订单"；已下单订单的 freeze_amount 已落库快照，不受影响
    "freeze_includes_rent": True,
    # 是否允许用户在租期日历上"手动点选"起止日期：
    #   True  = 快捷预设 + 日历手选都可用（默认）
    #   False = 只能用顶部快捷预设；日历仍展示选中区间但点选被禁用
    "allow_manual_date_pick": True,
    # 是否允许价格阶梯里日租金为 0（租押分离场景）：
    #   False = 硬性规则，日租金必须 > 0（默认，防漏配 0 元白嫖）
    #   True  = 允许某段日租金填 0（租金另行/线下处理，仅冻押金担保）
    "allow_zero_rent": False,
    # 零价兜底：商品起价恰好为 0 时，接口强制返回此值（元/天），只替换 0、不动其它价格。
    #   仅在 allow_zero_rent=False（正常租赁）时生效；
    #   allow_zero_rent=True（租押分离）时自动关闭，0 照实返回。
    "min_price_floor": 20.0,
    # 光影库存系统特权 Token（boss 在光影小程序设置页生成后粘贴到这里）。
    # 空 = 未对接，发货时不加载商品卡片。接口地址写死在 inventory_client.py。
    "inventory_api_token": "",
    # 发货时"货号"是否必填：False = 选填（默认），True = 必填
    "ship_huohao_required": False,
    # 待免押订单超时自动取消（死单清理）：
    #   True  = 下单后 24 小时仍未完成免押/付押金的订单自动取消（默认）
    #   False = 不自动取消，订单一直停留在"待免押"，用户随时可回来继续支付
    # 注：取消前会先向支付宝对账，已付款/已冻结的订单会推进为待发货而不是被取消。
    "auto_cancel_stale_audit": True,
}


def _load() -> dict:
    if not _PATH.exists():
        return {}
    try:
        return json.loads(_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def all_settings() -> dict:
    """返回完整配置（默认值合并文件值），任何 key 都保证存在。"""
    data = dict(_DEFAULTS)
    data.update(_load())
    return data


def get(key: str, default: Any = None) -> Any:
    s = all_settings()
    return s.get(key, default if default is not None else _DEFAULTS.get(key))


def update(patch: dict) -> dict:
    """合并更新；只接受 _DEFAULTS 里声明过的 key，防止误写未知字段。"""
    if not isinstance(patch, dict):
        raise ValueError("patch must be dict")
    allowed = set(_DEFAULTS.keys())
    clean = {k: v for k, v in patch.items() if k in allowed}
    with _lock:
        cur = _load()
        cur.update(clean)
        _save(cur)
    # 改了 alipay_app_id 后 SDK client 需要重建
    if "alipay_app_id" in clean:
        try:
            from app import alipay_client
            alipay_client.reset_client()
        except Exception:
            pass
    return all_settings()
