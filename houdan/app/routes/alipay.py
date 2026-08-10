"""支付宝/芝麻信用免押接口（全部走 alipay-sdk-python 真实调用）。

详见 docs/IDENTITY_AND_CREDIT_FLOW.md。
"""
import sys
import time
import uuid
from flask import Blueprint, request
from app.response import ok, fail
from app.alipay_client import get_client
from app.config import AlipayConfig
from app.notify_dedup import already_processed
from app.current_user import current_user, current_user_id, update_current_user

bp = Blueprint("alipay", __name__)


# =================== 异步通知公共工具 ===================
# 支付宝要求 notify 处理成功后必须输出纯文本 "success"（不带任何 HTML/JSON/换行）。
# 否则支付宝认为商户处理失败，会按 4m/10m/10m/1h/2h/6h/15h 共 8 次递增重试，
# 最终在 25 小时后停止；这期间订单状态可能严重不一致，必须严格遵守。
_NOTIFY_OK   = ("success", 200, {"Content-Type": "text/plain; charset=utf-8"})
_NOTIFY_FAIL = ("fail",    200, {"Content-Type": "text/plain; charset=utf-8"})


def _read_notify_params() -> dict:
    """支付宝异步通知 Content-Type 是 application/x-www-form-urlencoded（UTF-8）。
    优先读 form；测试场景允许直接发 JSON。
    """
    if request.form:
        return request.form.to_dict(flat=True)
    return request.get_json(silent=True) or {}


def _log_notify(channel: str, params: dict, verified: bool, business_ok: bool, extra: str = "") -> None:
    """统一打 notify 日志：① stderr 给 journalctl；② notify_log 给后台页可视化。"""
    keys = ("notify_id", "out_trade_no", "out_order_no", "trade_no", "auth_no",
            "operation_id", "operation_type", "trade_status", "status", "amount")
    short = {k: params.get(k) for k in keys if params.get(k) is not None}
    print(
        f"[alipay-notify] ch={channel} verify={verified} biz={business_ok} "
        f"env={AlipayConfig.ENV} fields={short} {extra}",
        file=sys.stderr,
        flush=True,
    )
    from app.notify_log import record
    record(
        channel=channel,
        params=params,
        verified=verified,
        business_ok=business_ok,
        duplicate=("duplicate" in extra),
        note=extra,
        raw_body=request.get_data(as_text=True) if request else "",
    )


# ============ 实名认证链路 ============
#
# 没有"identity/verify"步骤：新应用拿不到支付宝预留姓名（auth_user 已废弃，
# my.getOpenUserInfo 只给昵称不给实名），所以无法做"用户输入 vs 支付宝预留"
# 比对。支付宝 alipay.user.certify.open.* 本身就闭环负责实人核验
# （人脸 ↔ 身份证照片 ↔ 公安库），不需要前置比对。

# certify_id 在支付宝侧的存活规则（务必跟"认证通过后 3 个月免重复 KYC"区分开，
# 后者说的是认证**结果**可复用，不是这个 id 还能再唤起一次人脸）：
#   · initialize 之后一直没认证 → 23 小时有效，超时作废
#   · 一旦走完一次认证（通过或失败）→ 该 id 即被消费，不能再次唤起
# 拿作废/已消费的 id 去 certify.open 生成 URL，唤起时支付宝端会直接落到
# 「身份验证失败 - 人气大爆发，一会再试试」兜底页。这里留 1 小时余量，
# 避免卡在过期边界上把废 id 发给前端。
CERTIFY_ID_TTL = 22 * 3600


@bp.post("/certify/init")
def certify_init():
    """实人认证初始化：alipay.user.certify.open.initialize（biz_code=FACE）。

    返回 certify_id 给前端，前端调 my.startAPVerify({certifyId}) 唤起活体页。

    复用策略（见上方 CERTIFY_ID_TTL 注释）：
      - 仅当旧 certify_id **没被消费过**且仍在 23 小时窗口内才复用，省一次 KYC 费用。
        典型场景：用户上次拿到 id 后取消了 / 中途退出，压根没走完认证。
      - 认证跑完一次（certify/query 拿到结论）就标记已消费，下次必定重新 init。
      - 用户重新提交不同姓名/身份证 → 强制重新 init（cert_no 跟 init 时绑定）。
    """
    body = request.get_json(silent=True) or {}
    name    = (body.get("name") or "").strip()
    id_card = (body.get("id_card") or "").strip()
    if len(name) < 2 or len(id_card) not in (15, 18):
        return fail(20011, "name / id_card 不合法")

    u = current_user()
    now = int(time.time())
    old_id    = (u.get("last_certify_id") or "").strip()
    old_at    = int(u.get("last_certify_at") or 0)
    old_name  = (u.get("real_name") or "").strip()
    old_card  = (u.get("id_card") or "").strip()
    # 老数据没有 last_certify_used 字段，无从判断是否已消费 → 保守当作已消费
    old_used  = u.get("last_certify_used", True)
    # 复用条件：身份信息没变 + 旧 id 未被消费 + 还在 23 小时有效期内
    reusable = (old_id and old_name == name and old_card == id_card
                and not old_used and (now - old_at) < CERTIFY_ID_TTL)

    client = get_client()

    if reusable:
        # 复用 certify_id 也必须重新生成 certify_url：URL 内包含时间戳和签名，每次唤起都要拿最新的
        try:
            open_res = client.certify_open(old_id)
        except Exception as e:
            return fail(20014, f"调用支付宝失败（certify.open）：{e}")
        return ok({
            "certify_id":  old_id,
            "certify_url": open_res.get("certify_url") or "",
            "reused":      True,
            "init_time":   old_at,
        }, "复用已有认证")

    outer_order_no = "CO" + uuid.uuid4().hex[:18].upper()
    try:
        init = client.certify_init(
            name=name, id_card=id_card, outer_order_no=outer_order_no,
            biz_code="FACE",
        )
    except Exception as e:
        return fail(20012, f"调用支付宝失败：{e}")

    certify_id = init.get("certify_id") or ""
    if not certify_id:
        return fail(20013, "支付宝未返回 certify_id")

    # 拿到 certify_id 后立刻调 certify.open 生成 url —— my.startAPVerify 必须 (url, certifyId) 同时传
    try:
        open_res = client.certify_open(certify_id)
    except Exception as e:
        return fail(20014, f"调用支付宝失败（certify.open）：{e}")

    update_current_user({
        "real_name":         name,
        "id_card":           id_card,
        "last_certify_id":   certify_id,
        "last_certify_at":   now,
        "last_certify_used": False,     # 刚建的 id，还没被任何一次认证消费
    })

    return ok({
        "outer_order_no": outer_order_no,
        "certify_id":     certify_id,
        "certify_url":    open_res.get("certify_url") or "",
        "reused":         False,
        "init_time":      now,
    }, "实人认证已初始化")


@bp.post("/certify/query")
def certify_query():
    """查询认证结果：alipay.user.certify.open.query。passed=true 才标 verified。"""
    body = request.get_json(silent=True) or {}
    certify_id = (body.get("certify_id") or "").strip()
    if not certify_id:
        return fail(20021, "缺少 certify_id")

    try:
        res = get_client().certify_query(certify_id)
    except Exception as e:
        return fail(20022, f"调用支付宝失败：{e}")

    # query 能拿到结论 = 用户确实走完了一次认证 → 这个 certify_id 已被支付宝消费掉，
    # 不能再唤起第二次；标记后下次 certify_init 会强制重新 initialize。
    patch = {}
    if (current_user().get("last_certify_id") or "").strip() == certify_id:
        patch["last_certify_used"] = True
    if res.get("passed"):
        patch["verified"] = True
        if body.get("phone"): patch["phone"] = body["phone"]
    if patch:
        update_current_user(patch)
    return ok({
        "certify_id":  certify_id,
        "passed":      bool(res.get("passed")),
        "fail_reason": res.get("fail_reason") or "",
        "verify_time": int(time.time()),
    })


# ============ 芝麻先享 + 信用免押 ============

@bp.post("/credit/sign")
def credit_sign():
    """芝麻履约签约：zhima.credit.payafteruse.creditbizorder.order。

    商户需要先在芝麻信用开通"履约"产品并拿到 product_code（落在 AlipayConfig.SCENE_CODE/SERVICE_ID）。
    返回的 agreement_no 给前端用 my.tradePay 唤起芝麻签约页。
    """
    body = request.get_json(silent=True) or {}
    # 是否够格签约由芝麻信用在支付宝端判定，商户拿不到也不需要本地分数。
    product_code = (body.get("product_code") or AlipayConfig.PRODUCT_CODE or "").strip()
    category     = (body.get("category") or AlipayConfig.service_id() or "").strip()
    if not product_code or not category:
        return fail(10003, "芝麻履约产品未配置（缺 product_code / category）")

    out_agreement_no = body.get("out_agreement_no") or "AG" + uuid.uuid4().hex[:18].upper()
    biz_no           = body.get("biz_no") or out_agreement_no
    extend_params    = body.get("extend_params") or None

    try:
        res = get_client().zhima_credit_sign(
            out_agreement_no=out_agreement_no,
            product_code=product_code,
            category=category,
            biz_no=biz_no,
            extend_params=extend_params,
        )
    except Exception as e:
        return fail(10002, f"调用芝麻签约失败：{e}")

    res["sign_time"] = int(time.time())
    return ok(res, "签约已下发")


@bp.post("/credit/freeze")
def credit_freeze():
    """创建预授权订单：alipay.fund.auth.order.app.freeze

    设计原则：**分流判断全部交给阿里**，商户只发一次 freeze 请求。
      - 签了「信用免押」产品（配了 SERVICE_ID）→ extra_param.serviceId 由 SDK 层注入；
        用户在阿里支付页会看到「芝麻信用免押」按钮，够格就免押、不够格就用余额/花呗。
      - 没签信用免押 → 只能走普通预授权（冻结余额/花呗/银行卡）。
      - 商户**不需要**也**拿不到**用户的真实芝麻分，由支付宝端判定是否够格。
      - 用户**最终走的渠道**（CREDITZHIMA / BALANCE / PCREDIT_PAY ...）在 notify_auth_freeze
        / auth.order.query 的 `payment_method` 字段里返回，商户落库即可。
    """
    body = request.get_json(silent=True) or {}
    amount = float(body.get("amount") or 0)
    if amount <= 0:
        return fail(10002, "冻结金额非法")

    # —— 按订单已发起冻结次数生成本次 out_order_no ——
    # 支付宝授权订单按 out_order_no 唯一，同一号重复发起会被拒"授权订单已存在"。
    # 用户在免押收银台点取消后回退押金，需要换一个全新的 out_order_no 才能再次冻结。
    # 首次裸订单号（与历史/在途订单一致），之后递增后缀 _A2/_A3…，由 notify/query 反查还原。
    from app.storage.repos import order_repo
    order_id = (body.get("out_order_no") or "").strip()
    _order = order_repo.get(order_id) if order_id else None
    if _order:
        attempt = int(_order.get("alipay_freeze_attempts") or 0) + 1
        out_order_no = order_id if attempt == 1 else f"{order_id}_A{attempt}"
    else:
        # 无订单上下文（极少数老入口/裸调用）：退回原默认行为，不带订单语义
        attempt = 1
        out_order_no = order_id or "RT" + uuid.uuid4().hex[:18].upper()
    out_request_no = body.get("out_request_no") or f"{out_order_no}_R{int(time.time())}"
    order_title    = body.get("order_title") or "观澜数码租赁押金"

    extra = {}
    if body.get("transport_category"):
        extra["transportCategory"] = body["transport_category"]

    # enable_pay_channels 由前端按业务流程决定：
    #   传 "CREDITZHIMA" → 强制只走信用免押渠道（用户跳到的是免押授权页）
    #   不传 / 空        → 不限渠道，让用户在阿里页选余额/花呗/银行卡（押金兜底）
    enable_pay_channels = (body.get("enable_pay_channels") or "").strip() or None

    print(
        f"[alipay-freeze] out_order_no={out_order_no} amount={amount} "
        f"enable_pay_channels={enable_pay_channels} "
        f"service_id={AlipayConfig.service_id()} category={AlipayConfig.scene_code()} "
        f"product_code={AlipayConfig.PRODUCT_CODE}",
        file=sys.stderr, flush=True,
    )

    client = get_client()
    try:
        res = client.auth_freeze_app(
            out_order_no=out_order_no,
            out_request_no=out_request_no,
            order_title=order_title,
            amount=amount,
            scene_code=body.get("scene_code"),
            enable_pay_channels=enable_pay_channels,
            extra_param=extra or None,
        )
    except Exception as e:
        return fail(10006, f"调用支付宝失败：{e}")

    # 把本次尝试号 + 当前生效 out_order_no/out_request_no 落库到订单上：
    #   - detail.query / order.query 接口必须 (out_order_no + out_request_no) 配对，读这里；
    #   - alipay_freeze_attempts 供下一次回退冻结继续递增后缀；
    #   - alipay_out_order_no 记录当前生效授权订单号（裸号或带后缀）。
    # 同一订单多次发起 freeze（免押→押金两阶段），覆盖为最近一次。
    try:
        if _order:
            order_repo.update(order_id, {
                "alipay_freeze_attempts":     attempt,
                "alipay_out_order_no":        out_order_no,
                "alipay_out_request_no":      out_request_no,
                "alipay_enable_pay_channels": enable_pay_channels or "",
            })
    except Exception:
        pass  # 落库失败不影响 freeze 主流程

    res["service_id"] = AlipayConfig.service_id() or ""
    return ok(res, "freeze 已下发")


# =================== 冻结对账 / 自动解冻公共工具 ===================
# audit 不再是"60 秒即死"的瞬时态（定时取消已改为可开关的 24h 死单清理），
# 取消与付款成功之间存在天然竞态：用户付款途中订单被取消（用户手动 / 超时清理），
# 冻结成功的通知随后才到。这组工具保证任何路径下"取消撞上冻结成功"时资金都能
# 原路退回，而不是静默悬挂在支付宝冻结池里。


def query_active_freeze(order: dict) -> dict:
    """按订单"当前生效"的授权订单号+配对 out_request_no 查询冻结状态。
    与 /credit/query 的取号逻辑一致；老订单无生效号字段时回退裸订单号。
    查询失败向上抛异常，由调用方决定阻塞还是放行。
    """
    oid = order.get("id") or ""
    active_oon   = (order.get("alipay_out_order_no") or "").strip() or oid
    active_reqno = (order.get("alipay_out_request_no") or "").strip()
    return get_client().auth_order_query(active_oon, out_request_no=active_reqno or None)


def is_frozen(res: dict) -> bool:
    """auth_order_query 结果是否表示"钱冻着"。

    detail.query 的授权单状态（order_status）枚举 INIT/AUTHORIZED/FINISH/CLOSED，
    只有 AUTHORIZED（授权成功、资金冻结中）算冻着：
      - INIT   = 授权单已创建但用户没完成授权（打开收银台即产生，冻结 ¥0）
      - FINISH = 冻结额已全部转支付，无剩余冻结
      - CLOSED = 已全额解冻
    FROZEN 兼容旧版 order.query 接口的返回。
    found 只代表"支付宝查得到这笔授权单记录"，与是否冻结成功无关，
    绝不能参与判断（曾导致无免押额度的用户 INIT 单被误推进待发货）。
    """
    return (res.get("status") or "").upper() in ("AUTHORIZED", "FROZEN")


def freeze_confirmed(order: dict) -> bool:
    """这单的押金是否**确实**冻结成功过——"能不能发货"的唯一依据。

    绝不能拿 alipay_auth_no 当代理指标：授权单一创建就有 auth_no（用户刚点开
    收银台、order_status=INIT、冻结 ¥0 时查询就能拿到），而 credit_query 为了
    解冻兜底会把它无条件落库。曾经据此判定"押金已冻结"，把一笔从未授权成功的
    0 元租金单一路推进到待发货并扣了库存（O6E5AB9BC2F15，2026-08-03）。

    freeze_succeeded_at 只在两种确凿证据下写入（见 mark_freeze_success）：
      - auth_order_query 返回 AUTHORIZED/FROZEN（is_frozen 为真）
      - freeze 异步通知 status=SUCCESS/FROZEN，且属于当前生效授权号
    """
    if order.get("freeze_succeeded_at"):
        return True
    # 老数据兜底：本字段上线前的订单没有它。已经履约到 audit 之后的订单当年也是
    # 走同一套 is_frozen/SUCCESS 判定推进的，不能因为字段缺失就集体判"未冻结"
    # （会误杀上百笔在租订单的押金授权倒计时）。operation_id 只由冻结通知写入。
    # audit 阶段不吃这个兜底，从严——待发货之前的判定必须有确凿证据。
    if (order.get("status") or "") in ("audit", "cancelled"):
        return False
    return bool((order.get("alipay_operation_id") or "").strip())


def mark_freeze_success(oid: str, order: dict | None = None) -> None:
    """落"押金确实冻住了"的时间戳，幂等。

    唯一写入口。调用方必须已经拿到确凿证据（is_frozen 为真 / 通知 SUCCESS），
    不要为了"让订单能往下走"在别处补写这个字段。
    """
    from app.storage.repos import order_repo
    if not oid:
        return
    o = order if order is not None else order_repo.get(oid)
    if not o or o.get("freeze_succeeded_at"):
        return
    order_repo.update(oid, {"freeze_succeeded_at": int(time.time())})


def dispatch_auto_unfreeze(order: dict, auth_no: str, amount: float, reason: str) -> bool:
    """对"已取消却冻结成功"的订单自动下发解冻，资金原路退回用户。

    安全边界（调用方负责保证）：只用于订单已取消/即将取消、且这笔授权确属该订单
    当前生效授权的场景；活订单的在押押金绝不走这里。
    解冻本身天然幂等安全：已解冻的授权再发解冻只会被支付宝拒绝，不可能多退。

    返回 True = 解冻请求已下发（或此前已下发过，幂等跳过）。
    """
    from app.storage.repos import order_repo
    oid = order.get("id") or ""
    if not oid or not auth_no or amount <= 0:
        print(f"[alipay-auto-unfreeze][ALERT] 订单 {oid} 无法自动解冻："
              f"auth_no={auth_no!r} amount={amount}，需人工核实",
              file=sys.stderr, flush=True)
        return False
    if order.get("unfreeze_dispatched_at"):
        return True  # 已有在途/完成的解冻请求，幂等跳过
    out_request_no = "UF" + uuid.uuid4().hex[:18].upper()
    try:
        uf = get_client().auth_unfreeze(
            auth_no=auth_no,
            out_request_no=out_request_no,
            amount=amount,
            remark="订单已取消，自动解冻押金",
        )
    except Exception as e:
        print(f"[alipay-auto-unfreeze][ALERT] 订单 {oid} 自动解冻失败：{e}，需人工核实",
              file=sys.stderr, flush=True)
        return False
    order_repo.update(oid, {
        "unfreeze_dispatched_at":  int(time.time()),
        "unfreeze_out_request_no": out_request_no,
        "unfreeze_amount":         amount,
        "auto_unfreeze_reason":    reason,
    })
    print(f"[alipay-auto-unfreeze] 订单 {oid} 已自动解冻 ¥{amount:.2f}"
          f"（reason={reason} status={uf.get('status')}）",
          file=sys.stderr, flush=True)
    return True


def freeze_pool_amount(order: dict, notified_amount) -> float:
    """自动解冻金额：优先用支付宝回传的本笔冻结金额，回落订单冻结快照。"""
    try:
        v = float(notified_amount or 0)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return float(order.get("freeze_amount") or order.get("deposit_freeze") or 0)


def _record_orphan_freeze(order: dict, params: dict) -> None:
    """同一订单续号重试（_A2/_A3…）后，非"当前生效号"的授权也冻结成功了——
    出现即说明用户让多个收银台都完成了支付，属于异常场景。
    不自动动资金（避免误解活订单依赖的押金），落标记 + 高优先级告警，人工核实后解冻。
    """
    from app.storage.repos import order_repo
    oid = order.get("id") or ""
    alerts = list(order.get("orphan_freeze_alerts") or [])
    oon = params.get("out_order_no") or ""
    if any(a.get("out_order_no") == oon for a in alerts):
        return  # 同一笔孤儿授权只记一次
    alerts.append({
        "out_order_no":   oon,
        "auth_no":        params.get("auth_no") or "",
        "out_request_no": params.get("out_request_no") or "",
        "amount":         params.get("amount") or "",
        "at":             int(time.time()),
    })
    order_repo.update(oid, {"orphan_freeze_alerts": alerts})
    print(f"[alipay-freeze][ALERT] 订单 {oid} 收到非当前生效授权的冻结成功通知 "
          f"out_order_no={oon} auth_no={params.get('auth_no')} amount={params.get('amount')}，"
          f"该笔资金不属于任何在途担保，需人工核实后解冻",
          file=sys.stderr, flush=True)


@bp.post("/credit/query")
def credit_query():
    """查询授权订单状态：alipay.fund.auth.order.query
    若已 FROZEN/AUTHORIZED，首次发现时尝试收取首期租金并推进到 send；
    首次收租失败后这里只查询状态，不会因用户刷新而再次扣款。
    """
    body = request.get_json(silent=True) or {}
    order_id = body.get("out_order_no")        # 前端传裸订单号
    if not order_id:
        return fail(10007, "缺少 out_order_no")
    # 查询要用"当前生效"的授权订单号 + 配对的 out_request_no（重试后是带后缀号），
    # 而非裸订单号；否则查不到支付宝侧实际冻结的那笔授权订单。老订单无该字段→回退裸号。
    from app.storage.repos import order_repo
    _order = order_repo.get(order_id)
    active_oon   = (_order.get("alipay_out_order_no") or order_id) if _order else order_id
    active_reqno = (_order.get("alipay_out_request_no") or "") if _order else ""
    try:
        res = get_client().auth_order_query(active_oon, out_request_no=active_reqno or None)
    except Exception as e:
        return fail(10008, f"查询失败：{e}")

    # payment_method 由阿里在用户实际付款后返回：CREDITZHIMA=芝麻信用免押 / BALANCE=余额 / ...
    # 由此判断走的是免押还是押金（替代旧的本地 flow 字段）
    res["is_credit"] = (res.get("payment_method") or "").upper() == "CREDITZHIMA"
    # 冻结成败的唯一判据，前端据此提示/刷新，不要在前端自行解读 status/found
    res["is_frozen"] = is_frozen(res)

    # 主动查询是异步 notify 的兜底，查到的 auth_no 必须同样落库：
    # 授权号若只靠 freeze 通知写入，通知不可达（本地联调）或丢失时订单会一直
    # 没有授权号，后续取消/归还会被误判成"未冻结押金"而漏发解冻。
    # 注意：这里写的号**不代表冻结成功**——授权单 INIT（用户还没授权、冻结 ¥0）
    # 也查得到 auth_no。判断"钱冻着"一律走 is_frozen / freeze_confirmed。
    if _order and res.get("auth_no") and not (_order.get("alipay_auth_no") or "").strip():
        order_repo.update(order_id, {"alipay_auth_no": res["auth_no"]})

    if is_frozen(res):
        if _order:
            mark_freeze_success(order_id, _order)
        if _order and _order.get("status") == "cancelled":
            # 取消撞上付款成功（用户付款途中取消 / 超时清理竞态）：
            # 订单已取消但钱冻着，自动解冻原路退回，不再静默悬挂
            dispatch_auto_unfreeze(
                _order,
                (res.get("auth_no") or _order.get("alipay_auth_no") or "").strip(),
                freeze_pool_amount(_order, res.get("amount")),
                reason="query_frozen_after_cancel",
            )
        else:
            from app.routes.orders import transition_freeze_done
            transition_freeze_done(order_id)   # 综合授权 → 自动收租金 → 待发货
    latest = order_repo.get(order_id) if _order else None
    if latest:
        res["order_status"] = latest.get("status") or ""
        res["rent_captured"] = bool(latest.get("rent_paid_at"))
        res["rent_capture_error"] = (
            latest.get("rent_capture_last_error") or latest.get("rent_payment_error") or ""
        )
    return ok(res)


#                                                                              #
# =========================== 异步通知端点群 ================================= #
#                                                                              #
# 所有端点都遵循同一处理顺序：
#   1) 解析 form 参数（UTF-8 urlencoded）
#   2) verify_notify 验签；失败 → 返回 "fail"，让支付宝继续重试，绝不走业务
#   3) already_processed 幂等去重；命中 → 直接 "success"（避免重复扣库存/打款）
#   4) 业务推进；任何异常 → 返回 "fail" 让支付宝重试
#   5) 成功 → 纯文本 "success"
#
# 支付宝服务端检测响应的字面值是 "success"（小写、无引号、无前后空白），
# 任何 JSON / HTML / 重定向都算失败。


# ----- 授权回调（oauth_callback_url）：开放平台合规检查用 -----
# 小程序场景实际走的是 my.getAuthCode + 后端 exchange_oauth_token，本端点几乎不会被访问。
# 但开放平台「授权回调地址」字段必填，要这里能 200 响应。
@bp.route("/oauth/callback", methods=["GET", "POST"])
def oauth_callback():
    code = request.args.get("auth_code") or request.args.get("code") or ""
    app_id = request.args.get("app_id") or ""
    return (
        f"<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
        f"<h2>授权回跳已收到</h2>"
        f"<p>auth_code: <code>{code or '（无）'}</code></p>"
        f"<p>app_id: <code>{app_id or '（无）'}</code></p>"
        f"<p style='color:#888;font-size:13px'>请回到小程序继续操作。</p>"
        f"</body></html>",
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )


# ----- 应用网关（gateway_url）：接收平台级消息（非业务通知） -----
# 区别于上面那些业务 notify：
#   notify_url    每次调 freeze/trade 等业务接口时单独传，接收该笔业务的状态变更
#   gateway_url   应用全局一个，接收平台消息：授权变更、模板消息订阅、公告等
#                 用 msg_method 字段区分消息类型，目前先做最小占位（验签 + success）
@bp.route("/notify/gateway", methods=["GET", "POST"])
def notify_gateway():
    params = _read_notify_params()
    msg_method = params.get("msg_method") or "unknown"

    # 平台消息有时没有签名（如健康检查），有签名才验
    if params.get("sign"):
        verified = get_client().verify_notify(dict(params))
        if not verified:
            _log_notify(f"gateway:{msg_method}", params, False, False, "verify failed")
            return _NOTIFY_FAIL

    _log_notify(f"gateway:{msg_method}", params, True, True, "received (no biz handler yet)")
    return _NOTIFY_OK


@bp.post("/notify/auth_freeze")
def notify_auth_freeze():
    """alipay.fund.auth.order.app.freeze 冻结通知。

    关键字段：
      - out_order_no   商户授权订单号
      - auth_no        支付宝授权号（解冻/转支付时要用）
      - operation_type=FREEZE
      - status=SUCCESS / FROZEN  （文档：枚举值 INIT/SUCCESS/CLOSED；
                                   旧版本/部分场景下会出现 FROZEN，这里都当成功处理）
      - amount         本次冻结金额
    """
    params = _read_notify_params()
    verified = get_client().verify_notify(dict(params))
    if not verified:
        _log_notify("auth_freeze", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("auth_freeze", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    out_order_no = params.get("out_order_no")
    status = params.get("status", "")
    try:
        # 支付宝回传的 out_order_no 可能带重试后缀（_A2…），先还原成本地订单号
        from app.routes.orders import order_id_from_out_order_no, transition_freeze_done
        from app.storage.repos import order_repo
        oid = order_id_from_out_order_no(out_order_no)
        order = order_repo.get(oid)

        # 同一订单可能发起过多次授权（续号 _A2/_A3…），通知必须先验明正身：
        # 只有"当前生效号"的通知才允许写 auth_no / 推进状态机。孤儿授权的通知
        # 若覆盖了 auth_no，将来解冻会解错笔，真正押着的那笔永远解不掉。
        active_oon = ((order.get("alipay_out_order_no") or "").strip() or oid) if order else ""
        is_active = bool(order) and out_order_no == active_oon

        if is_active:
            # 把 auth_no / out_request_no 落库到订单上（detail.query 接口需要）。
            # 与 status 无关：CLOSED（授权关闭）的通知也要落号，否则后续查不到这笔。
            # 同理它也**不代表冻结成功**，成功标记只在下面 SUCCESS 分支里写。
            patch = {}
            if params.get("auth_no"):        patch["alipay_auth_no"] = params["auth_no"]
            if params.get("out_request_no"): patch["alipay_out_request_no"] = params["out_request_no"]
            if params.get("operation_id"):   patch["alipay_operation_id"] = params["operation_id"]
            if patch:
                order_repo.update(oid, patch)

        if status in ("SUCCESS", "FROZEN") and order:
            if not is_active:
                _record_orphan_freeze(order, params)
            elif order.get("status") == "cancelled":
                # 取消撞上付款成功：订单已取消但这笔押金刚冻结成功，自动解冻退回
                dispatch_auto_unfreeze(
                    order,
                    (params.get("auth_no") or "").strip(),
                    freeze_pool_amount(order, params.get("amount")),
                    reason="freeze_after_cancel",
                )
            else:
                # 通知已是"冻结成功"的确凿证据，先立字据再推进：transition_freeze_done
                # 见到 freeze_succeeded_at 就不必再向支付宝查一次。
                mark_freeze_success(oid, order)
                transition_freeze_done(out_order_no)  # audit→send；其余状态幂等忽略
        _log_notify("auth_freeze", params, True, True)
        return _NOTIFY_OK
    except Exception as e:
        _log_notify("auth_freeze", params, True, False, f"biz err: {e}")
        return _NOTIFY_FAIL


@bp.post("/notify/auth_unfreeze")
def notify_auth_unfreeze():
    """alipay.fund.auth.order.unfreeze 解冻通知。

    与 freeze 共用 operation 通知通道，区分点：
      - operation_type=UNFREEZE
      - status=SUCCESS 表示本次解冻已划回买家账户
    """
    params = _read_notify_params()
    if not get_client().verify_notify(dict(params)):
        _log_notify("auth_unfreeze", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("auth_unfreeze", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    out_order_no = params.get("out_order_no")
    op_type = params.get("operation_type", "UNFREEZE")
    status = params.get("status", "")
    try:
        if op_type == "UNFREEZE" and status == "SUCCESS":
            from app.routes.orders import transition_unfreeze_done
            transition_unfreeze_done(out_order_no)
        _log_notify("auth_unfreeze", params, True, True)
        return _NOTIFY_OK
    except Exception as e:
        _log_notify("auth_unfreeze", params, True, False, f"biz err: {e}")
        return _NOTIFY_FAIL


@bp.post("/notify/auth_pay")
def notify_auth_pay():
    """alipay.fund.auth.operation.detail.pay 预授权转支付通知。

    用户逾期 / 损坏赔付时，把冻结额度直接划走（解冻并同时扣款）。
    关键字段：
      - operation_type=PAY
      - status=SUCCESS
      - trade_no       生成的真实交易号
      - out_order_no   原授权订单号
    """
    params = _read_notify_params()
    if not get_client().verify_notify(dict(params)):
        _log_notify("auth_pay", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("auth_pay", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    out_order_no = params.get("out_order_no")
    status = params.get("status", "")
    try:
        if status == "SUCCESS":
            from app.routes.orders import transition_auth_pay_done
            transition_auth_pay_done(out_order_no)
        _log_notify("auth_pay", params, True, True)
        return _NOTIFY_OK
    except Exception as e:
        _log_notify("auth_pay", params, True, False, f"biz err: {e}")
        return _NOTIFY_FAIL


@bp.post("/notify/trade")
def notify_trade():
    """alipay.trade.* 一般交易通知（pay / create / wap pay 等）。

    租赁场景里通常用于补差价或租金扣款。
    关键字段：trade_status (WAIT_BUYER_PAY / TRADE_SUCCESS / TRADE_FINISHED / TRADE_CLOSED)
    """
    params = _read_notify_params()
    if not get_client().verify_notify(dict(params)):
        _log_notify("trade", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    # 校验 app_id 防止串号（生产环境强烈建议开启）
    app_id_in = params.get("app_id")
    expected_app_id = AlipayConfig.app_id()
    if expected_app_id and app_id_in and app_id_in != expected_app_id:
        _log_notify("trade", params, True, False, f"app_id mismatch: {app_id_in}")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("trade", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    out_trade_no = params.get("out_trade_no")
    trade_status = params.get("trade_status", "")
    try:
        # 把状态变更写回扣款流水（预授权扣款 alipay.trade.pay 走这条 notify）
        if out_trade_no:
            from app.storage.repos import trade_repo
            t = trade_repo.get(out_trade_no)
            if t:
                patch: dict = {}
                if trade_status:
                    patch["status"] = trade_status
                if params.get("trade_no"):       patch["trade_no"]       = params["trade_no"]
                if params.get("buyer_logon_id"): patch["buyer_logon_id"] = params["buyer_logon_id"]
                if params.get("gmt_payment"):    patch["gmt_payment"]    = params["gmt_payment"]
                if params.get("receipt_amount"):
                    try: patch["receipt_amount"] = float(params["receipt_amount"])
                    except Exception: pass
                if trade_status == "TRADE_CLOSED" and not t.get("closed_at"):
                    patch["closed_by"] = "notify"
                    patch["closed_at"] = int(time.time())
                if patch:
                    trade_repo.update(out_trade_no, patch)
        if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"):
            from app.routes.orders import complete_renewal
            complete_renewal(
                out_trade_no,
                trade_no=params.get("trade_no") or "",
                raw=dict(params),
            )
        _log_notify("trade", params, True, True)
        return _NOTIFY_OK
    except Exception as e:
        _log_notify("trade", params, True, False, f"biz err: {e}")
        return _NOTIFY_FAIL


@bp.post("/notify/trade_refund")
def notify_trade_refund():
    """alipay.trade.refund 退款异步通知。

    支付宝退款本身是同步接口，但银行卡/部分场景会再发异步通知确认资金最终到账。
    关键字段：out_trade_no / out_request_no / refund_fee / gmt_refund / trade_status
    """
    params = _read_notify_params()
    if not get_client().verify_notify(dict(params)):
        _log_notify("trade_refund", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("trade_refund", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    out_trade_no   = params.get("out_trade_no") or ""
    out_request_no = params.get("out_request_no") or ""
    try:
        # 写回 trade_repo.refunds 里对应那条
        if out_trade_no and out_request_no:
            from app.storage.repos import trade_repo
            t = trade_repo.get(out_trade_no)
            if t:
                refunds = list(t.get("refunds") or [])
                for i, r in enumerate(refunds):
                    if r.get("out_request_no") == out_request_no:
                        refunds[i] = {
                            **r,
                            "status":      "REFUND_SUCCESS",
                            "fund_change": "Y",
                            "refund_at":   r.get("refund_at") or int(time.time()),
                        }
                        break
                trade_repo.update(out_trade_no, {"refunds": refunds})
                # 重算累计
                total = sum(float(r.get("amount") or 0)
                            for r in refunds if r.get("status") == "REFUND_SUCCESS")
                trade_repo.update(out_trade_no, {"refunded_amount": round(total, 2)})

        # 业务态推进占位（当前 transition_trade_refunded 不强改主状态机）
        from app.routes.orders import transition_trade_refunded
        transition_trade_refunded(out_trade_no)
        _log_notify("trade_refund", params, True, True)
        return _NOTIFY_OK
    except Exception as e:
        _log_notify("trade_refund", params, True, False, f"biz err: {e}")
        return _NOTIFY_FAIL


@bp.post("/notify/zhima")
def notify_zhima():
    """芝麻信用相关回调（履约状态变更、信用服务退订等）。

    芝麻信用的回调字段较灵活（zm_service_id / agreement_no / status 等），
    这里先做验签 + 落日志，业务层后续按需要解析。
    """
    params = _read_notify_params()
    if not get_client().verify_notify(dict(params)):
        _log_notify("zhima", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("zhima", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    _log_notify("zhima", params, True, True)
    return _NOTIFY_OK


@bp.post("/notify/merchant_order_sync")
def notify_merchant_order_sync():
    """alipay.merchant.order.sync 履约状态回调。

    支付宝端发起的状态变更会反推回来，例如：
      - 用户在「我的-订单」点「确认收货」→ op_code=SIGN / status 变化
      - 用户点「确认完成」→ op_code=COMPLETE
      - 退款 / 退订发起 → op_code=REFUND
    具体 op_code / status 枚举与商家在开放平台签约的订单类型 (SERVICE_ORDER)
    有关，回调体里还会带原 ext_info / logistics_info 的镜像。

    **当前实现只做验签 + 落日志，不主动推进订单状态机。**
    运营在「回调日志」页按 channel=merchant_order_sync 即可看到所有事件，
    业务层后续要主动推进时再读这里的 params 解析。
    """
    params = _read_notify_params()
    if not get_client().verify_notify(dict(params)):
        _log_notify("merchant_order_sync_notify", params, False, False, "verify failed")
        return _NOTIFY_FAIL

    # app_id 校验防止串号（其他通知通道都做了，这里也对齐）
    app_id_in = params.get("app_id")
    expected_app_id = AlipayConfig.app_id()
    if expected_app_id and app_id_in and app_id_in != expected_app_id:
        _log_notify("merchant_order_sync_notify", params, True, False, f"app_id mismatch: {app_id_in}")
        return _NOTIFY_FAIL

    if already_processed(params):
        _log_notify("merchant_order_sync_notify", params, True, True, "duplicate, skip biz")
        return _NOTIFY_OK

    # 把订单号 + 用户动作摘要写到 note 里，运营列表一眼能看出"哪个订单做了什么"
    op_code = params.get("op_code") or params.get("operation_code") or ""
    status  = params.get("status") or ""
    biz_no  = params.get("out_biz_no") or params.get("out_order_no") or ""
    note = f"out_biz_no={biz_no} op_code={op_code or '-'} status={status or '-'}"

    _log_notify("merchant_order_sync_notify", params, True, True, note)
    return _NOTIFY_OK


@bp.post("/credit/unfreeze")
def credit_unfreeze():
    """解冻预授权：alipay.fund.auth.order.unfreeze。

    入参：auth_no（freeze 返回的支付宝授权号）、amount（解冻金额）、
          remark（备注，可空）。
    """
    body = request.get_json(silent=True) or {}
    auth_no = (body.get("auth_no") or "").strip()
    amount = float(body.get("amount") or 0)
    if not auth_no:
        return fail(10004, "缺少 auth_no")
    if amount <= 0:
        return fail(10004, "amount 必须 > 0")

    out_request_no = body.get("out_request_no") or "UF" + uuid.uuid4().hex[:18].upper()
    try:
        res = get_client().auth_unfreeze(
            auth_no=auth_no,
            out_request_no=out_request_no,
            amount=amount,
            remark=body.get("remark") or "",
        )
    except Exception as e:
        return fail(10005, f"调用支付宝失败：{e}")

    res["unfreeze_time"] = int(time.time())
    return ok(res, "解冻已下发")


@bp.post("/order/sync")
def order_sync():
    """商家订单履约状态同步：alipay.merchant.order.sync。"""
    body = request.get_json(silent=True) or {}
    out_biz_no = (body.get("out_order_no") or body.get("out_biz_no") or "").strip()
    order_type = (body.get("order_type") or "SERVICE_ORDER").strip()
    status     = (body.get("status") or "").strip()
    amount     = float(body.get("amount") or 0)
    if not out_biz_no or not status:
        return fail(10006, "out_order_no / status 必填")

    try:
        res = get_client().merchant_order_sync(
            out_biz_no=out_biz_no,
            order_type=order_type,
            status=status,
            amount=amount,
            buyer_id=body.get("buyer_id") or current_user_id(),
            extend_info=body.get("extend_info") or None,
        )
    except Exception as e:
        return fail(10007, f"调用支付宝失败：{e}")

    res["sync_time"] = int(time.time())
    return ok(res, "订单同步已下发")
