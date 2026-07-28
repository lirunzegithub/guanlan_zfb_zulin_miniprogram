"""光影库存系统对接客户端。

凭特权 Token（boss 在光影小程序设置页生成，粘贴到本系统后台设置）
按货号查询商品卡片信息（不含价格）。接口地址写死，不可配置。
"""
from __future__ import annotations

import requests

from app import settings

# 光影曳动库存系统后台地址（写死，不支持修改）
INVENTORY_API_BASE = "https://guangying.lirunze.top"

# 状态码：ok / not_configured / not_found / error
STATUS_OK = "ok"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"


def is_configured() -> bool:
    return bool((settings.get("inventory_api_token") or "").strip())


def fetch_item_by_huohao(huohao: str) -> tuple[str, dict | str]:
    """按货号查询光影系统商品。

    返回 (status, payload)：
    - ("ok", item_dict)            查询成功
    - ("not_configured", msg)      未配置 token
    - ("not_found", msg)           货号不存在
    - ("error", msg)               token 无效 / 网络错误等
    """
    token = (settings.get("inventory_api_token") or "").strip()
    if not token:
        return STATUS_NOT_CONFIGURED, "未配置光影库存系统特权Token"

    huohao = (huohao or "").strip()
    if not huohao:
        return STATUS_ERROR, "货号为空"

    try:
        resp = requests.post(
            f"{INVENTORY_API_BASE}/openapi_item_by_huohao",
            headers={"Authorization": f"Bearer {token}"},
            json={"huohao": huohao},
            timeout=5,
        )
    except requests.RequestException as e:
        return STATUS_ERROR, f"库存系统连接失败: {e}"

    if resp.status_code == 401:
        return STATUS_ERROR, "特权Token无效或已被删除，请在后台设置中更新"

    try:
        body = resp.json()
    except ValueError:
        return STATUS_ERROR, f"库存系统响应异常（HTTP {resp.status_code}）"

    if resp.status_code == 404 or body.get("code") == 404:
        return STATUS_NOT_FOUND, f"货号 {huohao} 在库存系统中不存在"

    if body.get("success") and isinstance(body.get("data"), dict):
        return STATUS_OK, body["data"]

    return STATUS_ERROR, body.get("message") or f"库存系统响应异常（HTTP {resp.status_code}）"


def fetch_items_by_huohaos(huohaos) -> dict:
    """批量按货号查询光影系统商品，返回 {货号: 商品卡片} 映射。

    专供订单列表页一次性拉取整屏实时数据。为不拖垮列表加载，本函数**从不抛异常**：
    未配置 token / 网络失败 / 响应异常 一律返回 {}，列表照常渲染（只是当次无光影数据）。
    """
    token = (settings.get("inventory_api_token") or "").strip()
    if not token:
        return {}

    # 去重保序 + 去空
    seen: list[str] = []
    for h in huohaos or []:
        h = str(h or "").strip()
        if h and h not in seen:
            seen.append(h)
    if not seen:
        return {}

    try:
        resp = requests.post(
            f"{INVENTORY_API_BASE}/openapi_items_by_huohaos",
            headers={"Authorization": f"Bearer {token}"},
            json={"huohaos": seen},
            timeout=8,
        )
        body = resp.json()
    except (requests.RequestException, ValueError):
        return {}

    data = body.get("data")
    if body.get("success") and isinstance(data, dict):
        return data
    return {}
