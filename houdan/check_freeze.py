"""押金冻结体检：逐单向支付宝核实"这笔押金到底冻没冻住"。

为什么需要它：订单上的 alipay_auth_no 只说明"支付宝有这笔授权单"，用户没完成授权
（order_status=INIT）或授权已关闭（CLOSED）时同样有授权号。历史上就是拿它当"已冻结"
的判据，把从未授权成功的订单推进到了待发货（O6E5AB9BC2F15 / O06F77AFBE298）。

用法（在服务器上、能连支付宝的环境里跑）：
    python check_freeze.py                # 体检所有在途订单（待发货/待收货/租赁中/待归还/逾期/核验中）
    python check_freeze.py O123 O456      # 只查指定订单
    python check_freeze.py --fix          # 顺手给"确认冻住了"的订单补 freeze_succeeded_at

只读接口（alipay.fund.auth.operation.detail.query），不动任何资金。
--fix 也只写本地的 freeze_succeeded_at 标记，不调用支付宝的写接口。
"""
import sys
import time

from app.routes.alipay import is_frozen, mark_freeze_success, query_active_freeze
from app.storage.repos import order_repo

IN_FLIGHT = ("send", "recv", "using", "return", "overdue", "return_inspecting")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_fix = "--fix" in sys.argv

    if args:
        orders = [o for o in (order_repo.get(a) for a in args) if o]
    else:
        orders = [o for s in IN_FLIGHT for o in order_repo.list(status=s)]
    orders.sort(key=lambda o: o.get("send_at") or o.get("created_at") or 0)

    bad, unknown, fixed = [], [], 0
    print(f"体检 {len(orders)} 单\n")
    for o in orders:
        oid = o.get("id") or ""
        try:
            res = query_active_freeze(o)
        except Exception as e:
            unknown.append((oid, str(e)[:60]))
            print(f"  ?  {oid} {o.get('status'):18} 查询失败：{str(e)[:60]}")
            continue
        raw = res.get("_raw") or {}
        frozen = is_frozen(res)
        line = (f"{oid} {o.get('status'):18} 授权单={res.get('status') or '-':10} "
                f"累计冻结=¥{raw.get('total_freeze_amount') or 0} "
                f"剩余=¥{raw.get('rest_amount') or 0} 应冻=¥{o.get('freeze_amount') or 0}")
        if frozen:
            print(f"  OK {line}")
            if do_fix and not o.get("freeze_succeeded_at"):
                mark_freeze_success(oid, o)
                fixed += 1
        else:
            bad.append(oid)
            print(f"  !! {line}   ← 押金未冻住")

    print(f"\n未冻住 {len(bad)} 单，查询失败 {len(unknown)} 单"
          + (f"，补标记 {fixed} 单" if do_fix else ""))
    if bad:
        print("需人工立即处理：" + " ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
