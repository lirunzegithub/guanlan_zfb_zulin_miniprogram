"""顺丰丰桥开放平台对接客户端（只用到「路由查询」一个服务）。

用途：拿运单的真实签收事件，驱动订单「待收货 → 租赁中」的跳变。
在此之前这条跳变是纯定时器（shipped_at + 物流免租期），包裹第 1 天就到了
订单也要等到第 3 天才变「租赁中」。

【本模块的铁律：从不抛异常】
    与 inventory_client 同风格。未配置 / 网络失败 / 响应异常 / 轨迹看不懂，
    一律返回"查不到"，由调用方回落到定时器保底。物流查询只能让跳变更早更准，
    绝不能因为顺丰接口抖动就把订单卡死在「待收货」。

【鉴权】丰桥统一接入协议（form 表单 POST）：
    partnerID   顾客编码（丰桥平台申请后获得，不是月结卡号）
    checkWord   校验码（与 partnerID 配对，仅用于本地签名，不上行）
    msgDigest   Base64(MD5(urlencode(msgData + timestamp + checkWord)))
    timestamp   毫秒时间戳
    Java 官方 demo 用 URLEncoder.encode（application/x-www-form-urlencoded 风格，
    空格转 '+'），Python 对应 quote_plus。两者仅在 '*' '~' 上有差异，而 msgData
    是 JSON + 运单号（纯字母数字），不会出现这两个字符，等价。

【已实测确认】2026-07-28 打丰桥沙箱（顾客编码 Y2AE7TV4）跑通全链路：
    1. 上面的 msgDigest 算法正确——正确签名回 A1000，故意改错回 A1006「数字签名无效」
    2. apiResultData 确实是 JSON **字符串**，需二次 json.loads（丰桥的历史设计）
    3. 网关**先查服务权限、再验签名**：接口没关联到应用时签名对错都回 A1004，
       所以 A1004 不要往签名方向排查，去丰桥后台关联接口
    4. 轨迹的状态码结构与签收判定，见 _FIRST_STATUS_SIGNED 处的实测码表
    5. 沙箱是**固定 mock**：任何运单号都回同一份 15 条轨迹，checkPhoneNo 填错也不拦。
       因此"运单不存在""手机号校验失败"这两种生产行为无法在沙箱验证，
       代码按"查不到就等下一轮、最终由定时器保底"处理，不依赖它们的具体错误码
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from urllib.parse import quote_plus

import requests

from app import settings

logger = logging.getLogger(__name__)

# 丰桥网关。沙箱供联调用（settings.sf_sandbox 打开），凭据两套不通用。
SF_API_PROD    = "https://bspgw.sf-express.com/std/service"
SF_API_SANDBOX = "https://sfapi-sbox.sf-express.com/std/service"

# 路由查询服务码
SERVICE_ROUTE_QUERY = "EXP_RECE_SEARCH_ROUTES"

# 【签收判定】实测沙箱真实轨迹后确定（2026-07-28）。顺丰同时给两套码：
#
#   opCode  firstStatusCode/Name  secondaryStatusCode/Name
#     50          1 已揽收               101 已揽收
#   30/36/31      2 运送中               201 运送中
#    204          3 派送中               301 派送中
#     80          4 已签收               401 已签收
#
# 以 firstStatusCode 为准，opCode 只在它缺失时兜底：
#   ① firstStatusCode 是顺丰对外承诺的**标准状态**，opCode 是内部操作码，
#      同一状态能对应好几个 opCode（运送中就有 30/36/31 三个），码表也更易变；
#   ② 更要紧的是「退件签收」——包裹退回商家、商家签收，那是设备正在回来的路上，
#      绝不能判成用户收到货。标准状态里退件签收是独立取值，用 firstStatusCode
#      天然区分得开；只看 opCode 或只看 remark 里的"已签收"字样则会误判，
#      后果是订单错误跳「租赁中」并把归还日算早。
_FIRST_STATUS_SIGNED = "4"          # firstStatusCode：已签收
_SIGNED_OP_CODES = frozenset({"80"})  # 仅在 firstStatusCode 缺失时启用

# 负向词：命中即一票否决，压过上面所有正向判定。
# "退件签收""拒收后退回"这类 remark 里都带"签收"二字，是最危险的误判来源。
_SIGNED_NEGATIVE = ("未签收", "拒收", "退件", "退回", "签收失败", "派送失败")

# 返回状态码
STATUS_SIGNED          = "signed"           # 已签收，payload = 签收时间 unix 秒
STATUS_IN_TRANSIT      = "in_transit"       # 查到轨迹但还没签收
STATUS_NOT_CONFIGURED  = "not_configured"   # 没配凭据
STATUS_ERROR           = "error"            # 网络/鉴权/响应异常

_TIMEOUT = 8


def is_configured() -> bool:
    """凭据齐全才算对接。任缺一项都视为未对接，全量走定时器保底。"""
    return bool(
        (settings.get("sf_partner_id") or "").strip()
        and (settings.get("sf_check_word") or "").strip()
    )


def _api_base() -> str:
    return SF_API_SANDBOX if settings.get("sf_sandbox") else SF_API_PROD


def _sign(msg_data: str, timestamp: str, check_word: str) -> str:
    """丰桥 msgDigest。"""
    raw = quote_plus(msg_data + timestamp + check_word)
    return base64.b64encode(hashlib.md5(raw.encode("utf-8")).digest()).decode("ascii")


def _post(service_code: str, msg_data: dict) -> tuple[bool, dict | str, str]:
    """调丰桥网关。返回 (ok, 业务数据 or 错误消息, 网关错误码)。不抛异常。

    第三个返回值给自检用：网关码能区分"权限没开(A1004)"和"校验码错(A1006)"，
    而这两种在用户看来都只是"调不通"，不告诉他具体是哪种就只能瞎试。
    没走到网关（未配置/网络失败）时为空串。
    """
    partner_id = (settings.get("sf_partner_id") or "").strip()
    check_word = (settings.get("sf_check_word") or "").strip()
    if not (partner_id and check_word):
        return False, "未配置顺丰丰桥凭据", ""

    # separators 去掉空格：签名对 msgData 逐字节敏感，序列化结果必须与上行完全一致
    payload = json.dumps(msg_data, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time() * 1000))

    try:
        resp = requests.post(
            _api_base(),
            data={
                "partnerID":   partner_id,
                "requestID":   uuid.uuid4().hex,
                "serviceCode": service_code,
                "timestamp":   timestamp,
                "msgDigest":   _sign(payload, timestamp, check_word),
                "msgData":     payload,
            },
            timeout=_TIMEOUT,
        )
        body = resp.json()
    except (requests.RequestException, ValueError) as e:
        return False, f"顺丰接口请求失败：{e}", ""

    # 网关层：A1000 = 成功，其余都是鉴权/限流/参数问题
    code = body.get("apiResultCode") or ""
    if code != "A1000":
        hint = ""
        if code == "A1004":
            # 实测：接口没关联到应用时签名对错都回这个码，别往签名方向排查
            hint = (f"——该顾客编码没有「{service_code}」的服务权限，"
                    f"需在丰桥应用里关联该接口并完成沙箱联调后申请上线")
        elif code == "A1006":
            hint = "——校验码填错了，或沙箱/生产环境与校验码不匹配"
        return False, (
            f"顺丰网关拒绝（{code}）：{body.get('apiErrorMsg') or '无错误描述'}{hint}"
        ), code

    # 业务层数据被包成 JSON 字符串再塞回来，需要二次解析
    raw = body.get("apiResultData")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            return False, "顺丰返回的 apiResultData 不是合法 JSON", code
    if not isinstance(raw, dict):
        return False, "顺丰返回结构异常", code

    if not raw.get("success"):
        return False, (
            f"顺丰业务失败（{raw.get('errorCode')}）：{raw.get('errorMsg') or '无错误描述'}"
        ), code
    return True, raw.get("msgData") or {}, code


def _parse_accept_time(s: str) -> int:
    """轨迹时间 'YYYY-MM-DD HH:MM:SS' → unix 秒。解析不了返回 0。

    顺丰回的是北京时间，按服务器本地时区解析——部署机固定 Asia/Shanghai，
    与全站其它时间戳（shipped_at 等）口径一致。
    """
    s = (s or "").strip()
    if not s:
        return 0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return int(time.mktime(time.strptime(s, fmt)))
        except ValueError:
            continue
    return 0


def _is_signed_route(route: dict) -> bool:
    """单条轨迹是不是「用户已签收」。判定顺序见 _FIRST_STATUS_SIGNED 处的说明。"""
    # 负向词一票否决，先于任何正向判定
    if any(neg in str(route.get("remark") or "") for neg in _SIGNED_NEGATIVE):
        return False
    first = str(route.get("firstStatusCode") or "").strip()
    if first:
        return first == _FIRST_STATUS_SIGNED
    # firstStatusCode 缺失（老响应/异常结构）才退回内部操作码
    return str(route.get("opCode") or "").strip() in _SIGNED_OP_CODES


def _pick_signed_route(routes: list) -> int:
    """从轨迹列表里挑签收时间。没有签收轨迹返回 0。

    取**最早**的一条：正常单只有一条；异常单（拒收后重派再签收）取最早的那次
    对用户更有利，也与"设备什么时候到用户手上"这个业务问题的答案一致。
    """
    stamps = [
        ts for r in routes or []
        if isinstance(r, dict) and _is_signed_route(r)
        and (ts := _parse_accept_time(r.get("acceptTime")))
    ]
    return min(stamps) if stamps else 0


def query_signed_at(waybill_no: str, check_phone: str = "") -> tuple[str, int | str]:
    """查一个运单是否已签收。

    Args:
        waybill_no:  顺丰运单号
        check_phone: 收件人手机号（本函数自行截后四位）。顺丰对非月结卡号下的
                     运单强制要求手机号后四位校验，月结单可不传；一律传上更稳，
                     且订单里本来就有收货人手机号快照。

    Returns:
        (STATUS_SIGNED, 签收时间 unix 秒)
        (STATUS_IN_TRANSIT, "")        查到了但还没签收
        (STATUS_NOT_CONFIGURED, msg)
        (STATUS_ERROR, msg)            网络/鉴权/解析失败，调用方应保持原状等下一轮
    """
    if not is_configured():
        return STATUS_NOT_CONFIGURED, "未配置顺丰丰桥凭据"

    no = (waybill_no or "").strip().upper()
    if not no:
        return STATUS_ERROR, "运单号为空"

    msg_data: dict = {
        "trackingType":   "1",     # 1 = 顺丰运单号
        "trackingNumber": [no],    # 接口本身支持批量，但 checkPhoneNo 是全局单值，
                                   # 不同订单收件人不同，只能一单一查
        "methodType":     "1",     # 1 = 标准查询
    }
    digits = "".join(ch for ch in (check_phone or "") if ch.isdigit())
    if len(digits) >= 4:
        msg_data["checkPhoneNo"] = digits[-4:]

    ok, data, _code = _post(SERVICE_ROUTE_QUERY, msg_data)
    if not ok:
        return STATUS_ERROR, str(data)

    resps = (data or {}).get("routeResps") or []
    if not isinstance(resps, list) or not resps:
        return STATUS_ERROR, "顺丰未返回该运单的轨迹"

    # 一单一查，取第一组即可；顺带核对 mailNo，防止串号
    routes: list = []
    for item in resps:
        if not isinstance(item, dict):
            continue
        if str(item.get("mailNo") or "").strip().upper() not in ("", no):
            continue
        routes.extend(item.get("routes") or [])

    signed_at = _pick_signed_route(routes)
    if signed_at:
        return STATUS_SIGNED, signed_at
    return STATUS_IN_TRANSIT, ""


# ============ 后台设置页的「测试连接」自检 ============

# 不传运单号时用它探连通性。生产环境下这个号必然查不到，但那不影响判断——
# 我们要的是网关层的 apiResultCode：能回 A1000 就说明编码/校验码/接口权限全通了。
_PROBE_WAYBILL = "SF0000000000000"


def _item(key: str, label: str, status: str, detail: str = "", hint: str = "") -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, "hint": hint}


def selfcheck(waybill_no: str = "") -> dict:
    """顺丰对接自检。只读，不改任何配置、不碰订单。

    Args:
        waybill_no: 可选。填了就顺带把签收判定也跑一遍，能直接看出这个单
                    会不会被判成"已签收"；不填只探连通性和鉴权。

    Returns:
        {summary: {...}, items: [...], routes: [...]}  与支付宝自检同构，前端复用同一套样式
    """
    partner = (settings.get("sf_partner_id") or "").strip()
    check_word = (settings.get("sf_check_word") or "").strip()
    sandbox = bool(settings.get("sf_sandbox"))
    items: list[dict] = []

    # ① 凭据齐备性（离线）
    if partner and check_word:
        items.append(_item("cred", "凭据已配置", "ok",
                           f"顾客编码 {partner}，校验码 {len(check_word)} 位"))
    else:
        missing = "、".join(
            n for n, v in (("顾客编码", partner), ("校验码", check_word)) if not v
        )
        items.append(_item(
            "cred", "凭据不完整", "fail", f"缺少：{missing}",
            "两项都填齐才会启用顺丰签收链路。留空不影响下单收款——"
            "顺丰单会和其它快递一样，按「发货时间 + 物流免租期」到点自动转「租赁中」",
        ))
        return {
            "summary": {"overall": "fail", "configured": False, "sandbox": sandbox,
                        "partner_id": partner, "ok": 0, "warn": 0, "fail": 1},
            "items": items, "routes": [],
        }

    items.append(_item("env", f"当前环境：{'沙箱（联调）' if sandbox else '生产'}",
                       "warn" if sandbox else "ok",
                       _api_base(),
                       "沙箱只回固定的模拟轨迹，任何运单号都返回同一份数据，"
                       "不能用来验证真实订单。正式运营前记得切回生产" if sandbox else ""))

    # ② 网关连通 + 鉴权 + 接口权限（一次调用同时验这三件事）
    probe_no = (waybill_no or "").strip().upper() or _PROBE_WAYBILL
    ok, data, code = _post(SERVICE_ROUTE_QUERY, {
        "trackingType": "1", "trackingNumber": [probe_no], "methodType": "1",
    })
    routes: list = []
    if code == "A1000":
        # 网关放行即代表编码/签名/接口权限全部正确；业务层查不到运单是另一回事
        items.append(_item("gateway", "网关鉴权通过", "ok",
                           "顾客编码、校验码、路由查询接口权限均正常（apiResultCode=A1000）"))
        if ok:
            for it in (data or {}).get("routeResps") or []:
                if isinstance(it, dict):
                    routes.extend(it.get("routes") or [])
        else:
            items.append(_item("business", "接口通了，但这个运单查不到轨迹", "warn",
                               str(data), "换一个真实的顺丰运单号再试"))
    elif code:
        items.append(_item("gateway", "网关拒绝", "fail", str(data),
                           "按上面括号里的错误码处置；A1004 是接口权限没开，"
                           "A1006 是校验码或环境不对"))
    else:
        items.append(_item("gateway", "连不上顺丰网关", "fail", str(data),
                           "检查服务器出网、以及丰桥后台的 IP 白名单是否已加本机公网 IP"))

    # ③ 签收判定（只有真拿到轨迹才跑）
    if routes:
        signed_at = _pick_signed_route(routes)
        if signed_at:
            items.append(_item(
                "verdict", "该运单判定为「已签收」", "ok",
                f"签收时间 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(signed_at))}"
                f"（共 {len(routes)} 条轨迹）",
                "真实订单走到这一步就会从「待收货」转「租赁中」",
            ))
        else:
            items.append(_item(
                "verdict", "该运单尚未签收", "ok",
                f"拉到 {len(routes)} 条轨迹，其中没有签收记录",
                "在途属正常。订单会保持「待收货」，到物流免租期仍未签收则由保底推进",
            ))

    counts = {"ok": 0, "warn": 0, "fail": 0}
    for it in items:
        counts[it["status"]] = counts.get(it["status"], 0) + 1
    overall = "fail" if counts["fail"] else ("warn" if counts["warn"] else "ok")

    return {
        "summary": {"overall": overall, "configured": True, "sandbox": sandbox,
                    "partner_id": partner, "waybill_no": probe_no,
                    "probed_with_placeholder": not (waybill_no or "").strip(), **counts},
        "items": items,
        # 只回最近 12 条，够运营肉眼核对，又不至于把整页刷屏
        "routes": [
            {
                "time":   r.get("acceptTime") or "",
                "status": r.get("secondaryStatusName") or r.get("firstStatusName") or "",
                "op":     str(r.get("opCode") or ""),
                "first":  str(r.get("firstStatusCode") or ""),
                "signed": _is_signed_route(r),
                "remark": (r.get("remark") or "")[:80],
            }
            for r in routes[-12:] if isinstance(r, dict)
        ],
    }
