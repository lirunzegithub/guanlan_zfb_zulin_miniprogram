"""后台登录防爆破：账号级失败锁定 + IP 级失败限流。

策略（均只统计"失败"，成功登录会清空该账号的计数）：
  账号级  同一用户名 15 分钟内失败 5 次 → 锁定 15 分钟，
          期间即使密码正确也拒绝（防止字典跑到正确密码时直接进门）。
  IP 级   同一 IP 10 分钟内失败 20 次 → 拒绝该 IP 的登录请求，
          直到窗口内失败数自然回落（覆盖"换用户名扫号"的场景）。

实现说明：
- 计数器放进程内存（threading.Lock + dict 滑动窗口），重启即清零。
  单进程部署下够用且零外部依赖；多 worker 部署时各进程独立计数，
  阈值等效放大 worker 倍数，仍远低于爆破所需次数，可接受。
- 用户名/IP 由请求方任意构造，dict 有被撑大的风险：每次写入超过
  _MAX_ENTRIES 时做一轮过期清理，防止内存被垃圾键占满。
- IP 取值：优先 X-Forwarded-For 首跳（Nginx 反代场景），否则 remote_addr。
"""
from __future__ import annotations

import threading
import time
from collections import deque

# 账号级：窗口内失败 N 次 → 锁定
ACCOUNT_WINDOW_SECONDS  = 15 * 60
ACCOUNT_MAX_FAILURES    = 5
ACCOUNT_LOCK_SECONDS    = 15 * 60

# IP 级：窗口内失败 N 次 → 拒绝（滑动窗口自然解除）
IP_WINDOW_SECONDS       = 10 * 60
IP_MAX_FAILURES         = 20

_MAX_ENTRIES = 10_000   # 键数超过此值时触发过期清理（防内存膨胀）

_lock = threading.Lock()
_account_failures: dict[str, deque] = {}   # username -> 失败时间戳队列
_account_locked_until: dict[str, int] = {} # username -> 锁定截止时间
_ip_failures: dict[str, deque] = {}        # ip -> 失败时间戳队列


def client_ip(request) -> str:
    """反代场景取 X-Forwarded-For 首跳，否则 remote_addr。"""
    xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return xff or (request.remote_addr or "unknown")


def _prune(q: deque, now: int, window: int) -> None:
    while q and q[0] <= now - window:
        q.popleft()


def _gc(now: int) -> None:
    """键数超限时清掉已过期的账号/IP 记录（持锁状态下调用）。"""
    if len(_account_failures) + len(_ip_failures) + len(_account_locked_until) < _MAX_ENTRIES:
        return
    for d, window in ((_account_failures, ACCOUNT_WINDOW_SECONDS),
                      (_ip_failures, IP_WINDOW_SECONDS)):
        for k in list(d.keys()):
            _prune(d[k], now, window)
            if not d[k]:
                del d[k]
    for k in list(_account_locked_until.keys()):
        if _account_locked_until[k] <= now:
            del _account_locked_until[k]


def check(username: str, ip: str) -> tuple[bool, str]:
    """登录前调用。返回 (是否放行, 拒绝原因)。放行时原因为空串。"""
    now = int(time.time())
    with _lock:
        locked_until = _account_locked_until.get(username, 0)
        if locked_until > now:
            wait_min = (locked_until - now + 59) // 60
            return False, f"失败次数过多，账号已锁定，请 {wait_min} 分钟后再试"

        q = _ip_failures.get(ip)
        if q is not None:
            _prune(q, now, IP_WINDOW_SECONDS)
            if len(q) >= IP_MAX_FAILURES:
                return False, "当前网络登录失败次数过多，请稍后再试"
    return True, ""


def record_failure(username: str, ip: str) -> None:
    """登录失败后调用：账号、IP 两个维度各记一笔；账号达到阈值即上锁。"""
    now = int(time.time())
    with _lock:
        _gc(now)

        q = _account_failures.setdefault(username, deque())
        _prune(q, now, ACCOUNT_WINDOW_SECONDS)
        q.append(now)
        if len(q) >= ACCOUNT_MAX_FAILURES:
            _account_locked_until[username] = now + ACCOUNT_LOCK_SECONDS
            q.clear()   # 上锁即清计数：解锁后从零重新累计

        qi = _ip_failures.setdefault(ip, deque())
        _prune(qi, now, IP_WINDOW_SECONDS)
        qi.append(now)


def record_success(username: str) -> None:
    """登录成功后调用：清空该账号的失败计数（IP 计数保留，防混合扫号）。"""
    with _lock:
        _account_failures.pop(username, None)
        _account_locked_until.pop(username, None)
