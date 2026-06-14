"""快递公司识别 + 元数据

当前只覆盖顺丰、京东两家。识别规则按"前缀字母 > 数字长度"的优先级，
冲突场景返回 unknown，让前端要求人工选择，避免猜错把通知挂错家。

运单号常见格式（按公开资料整理，2024 年仍稳定有效）：
  顺丰  - 12 位纯数字（电子面单最常见，如 770100000000）
        - 15 位纯数字（部分新版面单）
        - "SF" 前缀 + 12~15 位数字（国际/特殊业务）
  京东  - "JD" 前缀 + 10~18 位数字/字母（如 JDV04123..., JDVA0...）
        - "100" 开头的 13~15 位纯数字（京东自营电子面单）

注意：纯 13 位数字两家都用，故未列入识别条件，避免错误识别。
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Courier:
    code: str        # 内部编码，与 alipay.merchant.order.sync 的 logistics_code 兼容
    name: str        # 展示用中文名
    alipay_code: str # 支付宝履约同步时使用的物流公司编码

    def to_dict(self) -> dict:
        return {"code": self.code, "name": self.name, "alipay_code": self.alipay_code}


# 编码沿用支付宝《物流公司编码表》中的简写，便于后续接 alipay.merchant.order.sync
COURIERS: dict[str, Courier] = {
    "SF":      Courier("SF",      "顺丰速运", "SF"),
    "JD":      Courier("JD",      "京东物流", "JD"),
    "unknown": Courier("unknown", "未识别",   ""),
}


# 识别规则按"前缀 > 数字长度"的顺序匹配，命中即返回。
# 第一项是 courier code，第二项是正则（已带 ^$）。
_RULES: tuple[tuple[str, re.Pattern], ...] = (
    # —— 字母前缀（最可靠）——
    ("SF", re.compile(r"^SF\d{10,18}$", re.IGNORECASE)),
    ("JD", re.compile(r"^JD[A-Z0-9]{8,18}$", re.IGNORECASE)),
    # —— 纯数字（按平台公开规则）——
    ("JD", re.compile(r"^100\d{10,12}$")),   # 100 开头 13~15 位 → 京东自营
    ("SF", re.compile(r"^\d{12}$")),         # 12 位纯数字 → 顺丰电子面单
    ("SF", re.compile(r"^\d{15}$")),         # 15 位纯数字 → 顺丰新版面单（且非 100 开头）
)


def normalize_no(no: str) -> str:
    """去空格 + 转大写，运单号本身不区分大小写。"""
    return (no or "").strip().replace(" ", "").replace("-", "").upper()


def identify(no: str) -> Courier:
    """根据运单号识别快递公司；命中不到返回 unknown。"""
    n = normalize_no(no)
    if not n:
        return COURIERS["unknown"]
    for code, pattern in _RULES:
        if pattern.match(n):
            return COURIERS[code]
    return COURIERS["unknown"]


def get(code: str) -> Courier | None:
    """按 code 取 Courier；不存在返回 None。"""
    return COURIERS.get((code or "").upper())


def is_supported(code: str) -> bool:
    """是否在已支持列表内（不含 unknown）。"""
    c = (code or "").upper()
    return c in COURIERS and c != "UNKNOWN"


def supported_list() -> list[dict]:
    """前端下拉框需要的列表（不含 unknown）。"""
    return [c.to_dict() for k, c in COURIERS.items() if k != "unknown"]
