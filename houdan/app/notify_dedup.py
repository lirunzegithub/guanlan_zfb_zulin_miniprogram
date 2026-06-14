"""支付宝异步通知幂等去重。

支付宝同一笔通知可能被推送多次（25h 内 8 次重试），业务必须保证幂等。
官方建议以 `notify_id` 作为唯一键（每次通知都不同，但同一业务事件下重复推送会相同）。
退而求其次，用 `out_trade_no + trade_no + trade_status` 或
`out_order_no + operation_id + operation_type` 拼成 key 也可。

当前实现：进程内 set，重启即丢；生产环境务必换 Redis SETNX 或 DB 唯一索引。
        - Redis: `SETNX notify:dedup:{key} 1 EX 86400 * 2`
        - DB:    在 notify_log 表 (key) 列上加 UNIQUE，插入冲突即为重复
"""
from __future__ import annotations

import threading
from typing import Optional

# 真实生产建议换成 Redis / DB；这里用进程内 set + 锁保线程安全
_seen: set[str] = set()
_lock = threading.Lock()
_MAX_KEEP = 50_000  # 防内存爆炸；满了清掉最早一半（FIFO 简化版：直接清空）


def _build_key(params: dict) -> Optional[str]:
    """从 notify 参数里挑出最稳的唯一标识。

    优先级：
      1. notify_id（支付宝官方推荐，每次推送都带）
      2. out_order_no + operation_id    （预授权类）
      3. out_trade_no + trade_no        （交易类）
      4. trade_no                       （兜底）
    """
    nid = params.get("notify_id")
    if nid:
        return f"nid:{nid}"

    oon = params.get("out_order_no")
    op  = params.get("operation_id")
    if oon and op:
        return f"auth:{oon}:{op}"

    otn = params.get("out_trade_no")
    tn  = params.get("trade_no")
    if otn and tn:
        return f"trade:{otn}:{tn}"
    if tn:
        return f"trade:{tn}"
    return None


def already_processed(params: dict) -> bool:
    """检查并登记。返回 True 表示这是重复通知，应直接回 success 不再走业务。

    设计为「检查+登记」原子操作：第一次返回 False，之后任何调用都返回 True。
    """
    key = _build_key(params)
    if not key:
        # 拿不到唯一键时不能拦截，让业务自己处理（更糟的是吞掉了某些回调）
        return False

    with _lock:
        if key in _seen:
            return True
        if len(_seen) >= _MAX_KEEP:
            _seen.clear()
        _seen.add(key)
        return False


def reset() -> None:
    """仅供测试用。"""
    with _lock:
        _seen.clear()
