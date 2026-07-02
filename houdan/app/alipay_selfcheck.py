"""支付宝密钥/凭据自检（公钥模式）。

本项目走 RSA 密钥对「公钥模式」（非证书模式），自检围绕三份 PEM 展开：
    rsa_keys/app_private_key.pem    应用私钥（本机签名用）
    rsa_keys/app_public_key.pem     应用公钥（上传到开放平台换支付宝公钥）
    rsa_keys/alipay_public_key.pem  支付宝公钥（验支付宝回包/回调用）

自检分两层：
  1) 本地离线检查：文件是否存在、能否解析、私钥⇄应用公钥是否配对（本地签名再验签）；
     以及 APP_ID / notify_base / 信用免押参数是否配齐。全部零网络、毫秒级。
  2) 联网探针（probe=True，默认开）：用零副作用接口 alipay.system.oauth.token 传一个
     假 code 打一次真实网关，根据返回的 sub_code 判定「本机私钥」与「开放平台上传的
     应用公钥」是否配套 —— 这是本地永远查不出、却最常踩坑的一项。

返回结构：{"summary": {...}, "items": [{key,label,status,detail,hint}], "fingerprints": {...}}
status ∈ ok / warn / fail。仅只读诊断，不改任何配置、不产生资金动作。
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.config import AlipayConfig

logger = logging.getLogger(__name__)

# 本地配对自检用的固定探针串（私钥签它、应用公钥验它）
_PAIR_MSG = "alipay-selfcheck-pairing"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _abs_path(rel_or_abs: str) -> Path:
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / rel_or_abs
    return p


def _read_raw(rel_or_abs: str) -> str:
    """原样读 PEM 文本；不存在返回空串。"""
    p = _abs_path(rel_or_abs)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _fingerprint(pem_body: str) -> str:
    """对去掉页眉页脚/换行后的 base64 密钥体取 MD5，返回冒号分隔的短指纹。

    只对「公钥/密钥体」做摘要，用于和开放平台后台肉眼核对；不涉及私钥明文外泄
    （私钥指纹同样只是其自身内容的摘要，无法反推）。
    """
    if not pem_body:
        return ""
    digest = hashlib.md5(pem_body.encode("utf-8")).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def _parse_public(pem_body: str):
    """用 SDK 同款 rsa 库解析公钥（openssl/PKCS#8 PEM）；失败抛异常。

    这里刻意不依赖 pycryptodome —— 直接走 alipay-sdk-python 验签时真正用的 rsa 库，
    保证「能解析」等价于「支付宝验签时能用」。
    """
    import rsa
    from alipay.aop.api.util.SignatureUtils import fill_public_key_marker
    return rsa.PublicKey.load_pkcs1_openssl_pem(fill_public_key_marker(pem_body))


def _item(key, label, status, detail="", hint=""):
    return {"key": key, "label": label, "status": status, "detail": detail, "hint": hint}


# ---------------------------------------------------------------------------
# 本地离线检查
# ---------------------------------------------------------------------------
def _check_local() -> list[dict]:
    items: list[dict] = []

    # 1. APP_ID
    app_id = AlipayConfig.app_id()
    if app_id:
        items.append(_item("app_id", "APP_ID 已配置", "ok", detail=app_id))
    else:
        items.append(_item(
            "app_id", "APP_ID 已配置", "fail",
            detail="未配置",
            hint="在本页「支付宝 / 小程序 APPID」里填写开放平台的 APPID。",
        ))

    # 2~4. 三份 PEM：存在 + 可用（走 SDK 真实签名/验签路径，等价于支付宝端能不能用）
    # 私钥用 config.app_private_key()（已做 PKCS#8→#1 归一），与生产完全同源。
    private_body = AlipayConfig.app_private_key()
    alipay_pub_body = AlipayConfig.alipay_public_key()
    from app.config import _read_pem
    app_pub_path = "rsa_keys/app_public_key.pem"  # 应用公钥路径未进 config，按约定固定
    app_pub_body = _read_pem(app_pub_path)

    priv_sig = None  # 缓存一份签名，供后面配对检查复用
    if not _read_raw(AlipayConfig.APP_PRIVATE_KEY_PATH):
        items.append(_item(
            "app_private_key", "应用私钥文件", "fail",
            detail=f"未找到 {AlipayConfig.APP_PRIVATE_KEY_PATH}",
            hint="把开放平台密钥工具生成的应用私钥放到该路径。",
        ))
    else:
        try:
            from alipay.aop.api.util.SignatureUtils import sign_with_rsa2
            priv_sig = sign_with_rsa2(private_body, _PAIR_MSG, "utf-8")
            items.append(_item("app_private_key", "应用私钥可用", "ok",
                               detail="能正常签名（RSA2）"))
        except Exception as e:
            items.append(_item(
                "app_private_key", "应用私钥可用", "fail",
                detail=f"签名失败：{e}",
                hint="私钥内容可能被截断/格式非法；PKCS#8 私钥需已装 pycryptodome 做归一。",
            ))

    if not _read_raw(AlipayConfig.ALIPAY_PUBLIC_KEY_PATH):
        items.append(_item(
            "alipay_public_key", "支付宝公钥文件", "fail",
            detail=f"未找到 {AlipayConfig.ALIPAY_PUBLIC_KEY_PATH}",
            hint="从开放平台「接口加签方式」下载支付宝公钥，保存到该路径。",
        ))
    else:
        try:
            key = _parse_public(alipay_pub_body)
            items.append(_item("alipay_public_key", "支付宝公钥可解析", "ok",
                               detail=f"RSA {key.n.bit_length()} 位"))
        except Exception as e:
            items.append(_item(
                "alipay_public_key", "支付宝公钥可解析", "fail",
                detail=f"解析失败：{e}",
                hint="确认粘贴的是「支付宝公钥」而非应用公钥，且内容完整。",
            ))

    app_pub_ok = False
    if not app_pub_body:
        items.append(_item(
            "app_public_key", "应用公钥文件", "warn",
            detail=f"未找到 {app_pub_path}",
            hint="缺应用公钥不影响签名，但无法做「私钥⇄公钥配对」自检。",
        ))
    else:
        try:
            key = _parse_public(app_pub_body)
            app_pub_ok = True
            items.append(_item("app_public_key", "应用公钥可解析", "ok",
                               detail=f"RSA {key.n.bit_length()} 位"))
        except Exception as e:
            items.append(_item(
                "app_public_key", "应用公钥可解析", "fail",
                detail=f"解析失败：{e}",
            ))

    # 5. 私钥 ⇄ 应用公钥 本地配对（用私钥签，用应用公钥验）
    # 注意：rsa 库 verify 在验签「不匹配」时是抛 VerificationError，而非返回 False；
    # 所以「配不上」正是我们要报 fail 的场景，不能笼统吞进 warn。
    if priv_sig is not None and app_pub_ok:
        from alipay.aop.api.util.SignatureUtils import verify_with_rsa
        try:
            paired = bool(verify_with_rsa(app_pub_body, _PAIR_MSG.encode("utf-8"), priv_sig))
        except Exception:
            paired = False
        if paired:
            items.append(_item(
                "key_pairing", "私钥 ⇄ 应用公钥 配对", "ok",
                detail="本地签名验签通过，二者是一对",
            ))
        else:
            items.append(_item(
                "key_pairing", "私钥 ⇄ 应用公钥 配对", "fail",
                detail="验签不通过：本机私钥与应用公钥不是同一对",
                hint="重新用密钥工具生成一对，或确认上传到开放平台的正是这份应用公钥。",
            ))

    # 6. notify_base（异步回调 + 图片绝对地址前缀）
    notify_base = AlipayConfig.notify_base()
    placeholder = AlipayConfig.NOTIFY_BASE.rstrip("/")
    if not notify_base or notify_base == placeholder:
        items.append(_item(
            "notify_base", "公网域名 notify_base", "warn",
            detail="未配置（仍为占位域名）",
            hint="不配则收不到支付宝异步通知、小程序图片也打不开；需主动 query 兜底。",
        ))
    elif not notify_base.startswith("https://"):
        items.append(_item(
            "notify_base", "公网域名 notify_base", "warn",
            detail=f"非 https：{notify_base}",
            hint="支付宝回调要求 https 已备案域名。",
        ))
    else:
        items.append(_item("notify_base", "公网域名 notify_base", "ok", detail=notify_base))

    # 7. 签名算法
    items.append(_item("sign_type", "签名算法", "ok", detail=AlipayConfig.SIGN_TYPE))

    # 8. 信用免押参数（缺了会降级成普通预授权）
    svc_id = AlipayConfig.service_id()
    scene = AlipayConfig.scene_code()
    miss = []
    if not svc_id:
        miss.append("SERVICE_ID")
    if not scene:
        miss.append("SCENE_CODE(category)")
    if miss:
        items.append(_item(
            "credit_config", "信用免押参数", "warn",
            detail="缺少：" + ", ".join(miss),
            hint="缺失会导致 freeze 降级为普通预授权（用户看到「选支付方式」而非免押授权页）。"
                 "可在后台「设置」里填写 SERVICE_ID / 业务类目。",
        ))
    else:
        items.append(_item(
            "credit_config", "信用免押参数", "ok",
            detail=f"serviceId={svc_id[:8]}… category={scene}",
        ))

    return items


# ---------------------------------------------------------------------------
# 联网探针：私钥 ⇄ 开放平台应用公钥 是否配套（+ 支付宝公钥验签）
# ---------------------------------------------------------------------------
# 判定关键词（sub_code / msg 里命中即视为签名被拒）
_SIGN_FAIL_TOKENS = ("sign", "signature", "验签", "签名")


def _check_online_probe() -> dict:
    """打一次 alipay.system.oauth.token（假 code），零副作用。

    - 网关明确回签名错误 → 私钥与平台应用公钥不匹配（fail）
    - 回其它业务错误（如 code 无效）→ 签名被接受，密钥配套 ok
    - SDK 抛验签异常 → 支付宝公钥填错（fail）
    """
    ready, reason = AlipayConfig.is_real_ready()
    if not ready:
        return _item(
            "online_probe", "联网验证密钥配套", "warn",
            detail=f"前置配置未就绪，跳过：{reason}",
        )

    try:
        from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
        from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
        from alipay.aop.api.request.AlipaySystemOauthTokenRequest import (
            AlipaySystemOauthTokenRequest,
        )
    except ImportError as e:
        return _item("online_probe", "联网验证密钥配套", "warn",
                     detail=f"SDK 未安装，跳过：{e}")

    cfg = AlipayClientConfig()
    cfg.server_url = AlipayConfig.gateway()
    cfg.app_id = AlipayConfig.app_id()
    cfg.app_private_key = AlipayConfig.app_private_key()
    cfg.alipay_public_key = AlipayConfig.alipay_public_key()
    cfg.sign_type = AlipayConfig.SIGN_TYPE

    try:
        client = DefaultAlipayClient(alipay_client_config=cfg, logger=logger)
        req = AlipaySystemOauthTokenRequest()
        req.grant_type = "authorization_code"
        req.code = "selfcheck_invalid_code"  # 故意用无效 code，只为验签名，不换真 token
        import json as _json
        raw = client.execute(req)
        body = _json.loads(raw) if isinstance(raw, str) else raw
        payload = (body or {}).get("alipay_system_oauth_token_response", body) or {}
        sub_code = str(payload.get("sub_code") or "")
        sub_msg = str(payload.get("sub_msg") or "")
        code = str(payload.get("code") or "")

        blob = (sub_code + " " + sub_msg).lower()
        if any(t in blob for t in _SIGN_FAIL_TOKENS):
            return _item(
                "online_probe", "联网验证密钥配套", "fail",
                detail=f"网关判定签名错误：sub_code={sub_code} sub_msg={sub_msg}",
                hint="本机应用私钥与开放平台上传的应用公钥不匹配：请把与本私钥配对的"
                     "应用公钥重新上传到开放平台，并确认 APPID 一致。",
            )
        # 走到这：签名被支付宝接受了（哪怕业务上因 code 无效而报错）
        return _item(
            "online_probe", "联网验证密钥配套", "ok",
            detail=f"签名通过（业务返回 code={code} sub_code={sub_code}，属预期的假 code 报错）",
        )
    except Exception as e:
        msg = str(e).lower()
        if any(t in msg for t in _SIGN_FAIL_TOKENS):
            return _item(
                "online_probe", "联网验证密钥配套", "fail",
                detail=f"验签异常：{e}",
                hint="多为「支付宝公钥」填错（验支付宝回包失败），或私钥与平台应用公钥不匹配。",
            )
        return _item(
            "online_probe", "联网验证密钥配套", "warn",
            detail=f"探针请求异常（网络/网关波动？）：{e}",
        )


# ---------------------------------------------------------------------------
# 指纹（供和开放平台后台肉眼核对）
# ---------------------------------------------------------------------------
def _fingerprints() -> dict:
    from app.config import _read_pem  # 复用同一套 PKCS#8→#1 归一，指纹才稳定
    return {
        "app_public_key":    _fingerprint(_read_pem("rsa_keys/app_public_key.pem")),
        "alipay_public_key": _fingerprint(_read_pem(AlipayConfig.ALIPAY_PUBLIC_KEY_PATH)),
        "app_private_key":   _fingerprint(_read_pem(AlipayConfig.APP_PRIVATE_KEY_PATH)),
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def run_selfcheck(probe: bool = True) -> dict:
    items = _check_local()
    if probe:
        items.append(_check_online_probe())

    fails = sum(1 for it in items if it["status"] == "fail")
    warns = sum(1 for it in items if it["status"] == "warn")
    oks = sum(1 for it in items if it["status"] == "ok")
    overall = "fail" if fails else ("warn" if warns else "ok")

    return {
        "summary": {"overall": overall, "ok": oks, "warn": warns, "fail": fails,
                    "total": len(items), "app_id": AlipayConfig.app_id(),
                    "env": AlipayConfig.ENV, "probed": probe},
        "items": items,
        "fingerprints": _fingerprints(),
    }
