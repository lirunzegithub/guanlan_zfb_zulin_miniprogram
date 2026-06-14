"""分段计费 (tiered pricing)。

数据结构：商品 price_tiers 是一组 {from, price} 段，from 严格递增，
首段 from==1，最后一段隐含覆盖到无穷天。租 N 天按 N 落在的段逐段累加。
"""
from __future__ import annotations
from typing import Iterable


def normalize_tiers(raw) -> list[dict]:
    """规范化：剔除非法项、按 from 升序、去重相邻同价段。

    若结果为空，回退成 [{from:1, price:0}]，让上层不至于崩。
    """
    out = []
    for t in (raw or []):
        try:
            f = int(t.get("from"))
            p = float(t.get("price"))
        except (TypeError, ValueError, AttributeError):
            continue
        if f < 1 or p < 0:
            continue
        out.append({"from": f, "price": p})
    out.sort(key=lambda x: x["from"])

    # 去掉 from 重复项（保留后者）
    dedup: list[dict] = []
    for t in out:
        if dedup and dedup[-1]["from"] == t["from"]:
            dedup[-1] = t
        else:
            dedup.append(t)

    # 折叠相邻同价段
    folded: list[dict] = []
    for t in dedup:
        if folded and folded[-1]["price"] == t["price"]:
            continue
        folded.append(t)

    if not folded:
        return [{"from": 1, "price": 0.0}]
    # 强制首段 from = 1
    if folded[0]["from"] != 1:
        folded[0] = {"from": 1, "price": folded[0]["price"]}
    return folded


def validate_tiers(raw) -> tuple[bool, str]:
    """严格校验（给后台保存接口用）：返回 (ok, errmsg)。"""
    if not isinstance(raw, list) or not raw:
        return False, "至少需要一段租金"
    last_from = 0
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            return False, f"第 {i+1} 段格式错误"
        try:
            f = int(t.get("from"))
            p = float(t.get("price"))
        except (TypeError, ValueError):
            return False, f"第 {i+1} 段：from/price 必须是数字"
        if p < 0:
            return False, f"第 {i+1} 段：单价不能为负"
        if i == 0 and f != 1:
            return False, "第一段必须从第 1 天起"
        if f <= last_from:
            return False, f"第 {i+1} 段：起始天必须大于上一段（已收到 {f}，需要 > {last_from}）"
        last_from = f
    return True, ""


def calc_amount(days: int, tiers: Iterable[dict]) -> float:
    """按分段累加 N 天总金额。"""
    days = max(0, int(days or 0))
    if days == 0:
        return 0.0
    segs = normalize_tiers(tiers)
    total = 0.0
    for i, seg in enumerate(segs):
        seg_from = seg["from"]
        if seg_from > days:
            break
        seg_end = (segs[i + 1]["from"] - 1) if i + 1 < len(segs) else days
        seg_end = min(seg_end, days)
        total += (seg_end - seg_from + 1) * seg["price"]
    return round(total, 2)


def substitute_zero_tiers(tiers: Iterable[dict], fallback: float) -> list[dict]:
    """把日租金恰好为 0 的分段替换成 fallback（只替换 0，非 0 原样）。
    调用方决定是否启用（如仅在 allow_zero_rent=False 时调用）。返回新列表，不改入参。
    """
    out: list[dict] = []
    for t in (tiers or []):
        t2 = dict(t)
        try:
            if float(t2.get("price") or 0) == 0:
                t2["price"] = float(fallback)
        except (TypeError, ValueError):
            pass
        out.append(t2)
    return out


def min_unit_price(tiers: Iterable[dict]) -> float:
    """所有段里最便宜的单价，用于「¥X/天起」展示。"""
    segs = normalize_tiers(tiers)
    return round(min(s["price"] for s in segs), 2)


def first_unit_price(tiers: Iterable[dict]) -> float:
    """首段单价（第 1 天的价格），兼容旧 price 字段。"""
    segs = normalize_tiers(tiers)
    return round(segs[0]["price"], 2)


def derive_price_curve(tiers: Iterable[dict], max_day: int = 30) -> list[dict]:
    """输出"第 N 天的日租金"折线关键节点，day ∈ [1, max_day]。

    每段在 [seg.from, next.from - 1] 内保持单价。绘图时：
    - 段起点画一个点
    - 段中段尾（next.from - 1）的"段尾水平延伸点"按需补：
      仅当下一段的 from 还离 max_day 较远（< max_day）时才补
    - 最后一段水平延伸到 max_day
    - 超过 max_day 的段不渲染（不让前端 clip 出 off-chart 重叠点）；
      前段的水平线被截到 max_day

    规避两类"两个点撞在 30 天右边缘"的视觉 bug：
      A) tier 切换点恰在 max_day  → 跳过段尾点，靠后续 max_day 起点收尾
      B) tier from 超过 max_day   → 直接截断，不让前端 clip 出 day=31+ 的 off-chart 点

    例：tiers=[{1,10},{7,5}], max_day=30 →
        [(1,10), (6,10), (7,5), (30,5)]
        视觉：1–6 水平 ¥10，6→7 陡降，7–30 水平 ¥5。

    例：tiers=[{1,100},{30,50}], max_day=30 →
        [(1,100), (30,50)]
        视觉：从 (1,100) 斜线到 (30,50)；右边缘只有一个点。
    """
    segs = normalize_tiers(tiers)
    if not segs:
        return []

    out: list[dict] = []
    for i, seg in enumerate(segs):
        seg_from = int(seg["from"])
        seg_price = round(seg["price"], 2)

        # B) 超过 max_day 的段：前段水平线延伸到 max_day，然后停
        if seg_from > max_day:
            if out and out[-1]["day"] < max_day:
                out.append({"day": max_day, "price": out[-1]["price"]})
            return out

        # 段起点（防御性：避免与上一个点 day 撞）
        if not out or out[-1]["day"] != seg_from:
            out.append({"day": seg_from, "price": seg_price})

        next_from = int(segs[i + 1]["from"]) if i + 1 < len(segs) else None

        if next_from is None:
            # 最后一段：水平延伸到 max_day
            if max_day > seg_from:
                out.append({"day": max_day, "price": seg_price})
        elif next_from >= max_day:
            # A) 下一段贴在 max_day 边界（或之外）：跳过段尾点，
            # 由下一次循环画 max_day 处的起点（或 break 时统一收尾）
            continue
        else:
            # 中间段：段尾水平延伸到下一段开始前 1 天
            step_end = next_from - 1
            if step_end > seg_from:
                out.append({"day": step_end, "price": seg_price})

    return out
