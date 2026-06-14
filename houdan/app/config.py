"""支付宝接入核心配置（纯硬编码，零环境变量依赖）

所有可调参数都直接写在本文件的 class 体里；改值就改这里，重启进程生效。
密钥本身仍以 PEM 文件形式放在 rsa_keys/ 下（避免把巨大密钥串写进源码），
但路径是写死的。
"""
from __future__ import annotations

from pathlib import Path


# ============================================================================
# PEM 文件读取（PKCS#8 ↔ PKCS#1 自动转换）
# ============================================================================
def _strip_pem(pem_text: str) -> str:
    lines = [ln for ln in pem_text.splitlines() if not ln.startswith("-----")]
    return "".join(lines).strip()


def _read_pem(path: str) -> str:
    """文件不存在返回空串；自动 PKCS#8→PKCS#1。"""
    if not path:
        return ""
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / path
    if not p.exists():
        return ""
    raw = p.read_text(encoding="utf-8")

    if "PUBLIC KEY" in raw or "RSA PRIVATE KEY" in raw:
        return _strip_pem(raw)

    # PKCS#8 私钥 → 转 PKCS#1
    try:
        from Crypto.PublicKey import RSA  # pycryptodome 已被 alipay-sdk-python 拉进
        key = RSA.importKey(raw)
        return _strip_pem(key.export_key("PEM", pkcs=1).decode("utf-8"))
    except Exception:
        return _strip_pem(raw)


# ============================================================================
# 配置主体
# ============================================================================
class AlipayConfig:

    # ── 0. 环境 ────────────────────────────────────────────
    # "prod" 生产 / "sandbox" 沙箱
    ENV = "prod"

    # ── 1. 网关 ────────────────────────────────────────────
    GATEWAY_PROD    = "https://openapi.alipay.com/gateway.do"
    GATEWAY_SANDBOX = "https://openapi-sandbox.dl.alipaydev.com/gateway.do"

    # ── 2. 身份凭证 ────────────────────────────────────────
    # APP_ID 现在改由 settings.json (alipay_app_id) 动态提供，下面这个常量仅作
    # 首次启动的 fallback；运行期一律通过 cls.app_id() 读取。
    # 在支付宝开放平台「我的应用」里拿到自己的 APPID 后填入（或在管理后台「设置」里配置）。
    APP_ID                 = ""          # 例如 "2021000000000000"
    APP_PRIVATE_KEY_PATH   = "rsa_keys/app_private_key.pem"
    ALIPAY_PUBLIC_KEY_PATH = "rsa_keys/alipay_public_key.pem"
    SIGN_TYPE              = "RSA2"

    # 接口内容加密（AES，开放平台「接口加密方式」里生成的对称密钥；base64 编码）
    # 配置后，需要加密的接口（如返回手机号/身份证号等 PII 字段）会自动走 AES 加解密。
    # 未启用接口加密则留空。
    AES_ENCRYPT_KEY        = ""          # 例如 "xxxxxxxxxxxxxxxxxxxxxx=="

    # ── 3. 异步通知 ────────────────────────────────────────
    # 改成你自己的公网 HTTPS 域名（支付宝异步通知会回调到这里）。
    NOTIFY_BASE = "https://your-domain.example.com"

    NOTIFY_URL_AUTH_FREEZE   = f"{NOTIFY_BASE}/api/alipay/notify/auth_freeze"
    NOTIFY_URL_AUTH_UNFREEZE = f"{NOTIFY_BASE}/api/alipay/notify/auth_unfreeze"
    NOTIFY_URL_AUTH_PAY      = f"{NOTIFY_BASE}/api/alipay/notify/auth_pay"
    NOTIFY_URL_TRADE         = f"{NOTIFY_BASE}/api/alipay/notify/trade"
    NOTIFY_URL_TRADE_REFUND  = f"{NOTIFY_BASE}/api/alipay/notify/trade_refund"
    NOTIFY_URL_ZHIMA         = f"{NOTIFY_BASE}/api/alipay/notify/zhima"
    # 商家订单履约同步回调：用户在支付宝端「已签收」「确认使用」等动作产生
    NOTIFY_URL_MERCHANT_ORDER_SYNC = f"{NOTIFY_BASE}/api/alipay/notify/merchant_order_sync"

    # 实人认证 return_url：小程序 my.startAPVerify 唤起不会真的跳转到这里，
    # 但 alipay 对 merchant_config.return_url 做格式校验，必须是合法 https URL。
    CERTIFY_RETURN_URL = f"{NOTIFY_BASE}/api/alipay/certify/return"

    # 应用网关（gateway_url）：开放平台后台「开发设置 → 应用网关」要填的地址，
    # 接收平台级消息（授权变更/模板消息订阅/公告等），区别于业务通知 notify_url
    GATEWAY_URL = f"{NOTIFY_BASE}/api/alipay/notify/gateway"

    # 授权回调地址（用于开放平台 OAuth 授权回跳）。小程序 my.getAuthCode 流程不会真用到，
    # 但开放平台「授权回调地址」字段要求填一个合法 URL 做合规检查。
    OAUTH_CALLBACK_URL = f"{NOTIFY_BASE}/api/alipay/oauth/callback"

    # ── 4. 信用免押 ────────────────────────────────────────
    PRODUCT_CODE        = "PRE_AUTH_ONLINE"
    ENABLE_PAY_CHANNELS = "CREDITZHIMA"
    # SCENE_CODE 实际上是要传给阿里 extra_param.category 的业务类目码，
    # 在开放平台「信用借还/信用免押」产品后台拿（如 RENT_3C / RENT_DIGITAL / RENT_AUTO ...）。
    # 留空 → 阿里识别不到信用借还业务，会把请求降级为普通预授权页（用户看到「选支付方式」而不是「免押授权页」）。
    SCENE_CODE          = "RENT_DIGITAL"
    # 在支付宝开放平台「信用服务管理」里创建信用借还服务后拿到的 SERVICE_ID，填入自己的。
    SERVICE_ID          = ""          # 例如 "2026000000000000000000000000"

    # ── 5. 信用服务守约链接 ─────────────────────────────────
    XINYONG_SHOUYUE_URL = (
        "alipays://platformapi/startapp"
        "?appId={APP_ID}"
        "&page=pages/order-detail/order-detail"
        "&query=id=${out_order_no}"
    )

    # ── 工具方法 ───────────────────────────────────────────
    @classmethod
    def app_id(cls) -> str:
        """优先取 settings.json 里的 alipay_app_id，没配回落到模块常量。"""
        try:
            from app.settings import get as _setting_get
            v = (_setting_get("alipay_app_id") or "").strip()
            if v:
                return v
        except Exception:
            pass
        return cls.APP_ID

    @classmethod
    def gateway(cls) -> str:
        return cls.GATEWAY_SANDBOX if cls.ENV == "sandbox" else cls.GATEWAY_PROD

    @classmethod
    def app_private_key(cls) -> str:
        return _read_pem(cls.APP_PRIVATE_KEY_PATH)

    @classmethod
    def alipay_public_key(cls) -> str:
        return _read_pem(cls.ALIPAY_PUBLIC_KEY_PATH)

    @classmethod
    def is_real_ready(cls) -> tuple[bool, str]:
        missing = []
        if not cls.app_id():                missing.append("APP_ID")
        if not cls.app_private_key():       missing.append("APP_PRIVATE_KEY 文件")
        if not cls.alipay_public_key():     missing.append("ALIPAY_PUBLIC_KEY 文件")
        if not cls.NOTIFY_URL_AUTH_FREEZE:
            return True, "ok（未配 NOTIFY_URL，收不到异步通知，需主动 query）"
        return (not missing), ("ok" if not missing else "缺少: " + ", ".join(missing))

    @classmethod
    def all_notify_urls(cls) -> dict:
        return {
            "auth_freeze":           cls.NOTIFY_URL_AUTH_FREEZE,
            "auth_unfreeze":         cls.NOTIFY_URL_AUTH_UNFREEZE,
            "auth_pay":              cls.NOTIFY_URL_AUTH_PAY,
            "trade":                 cls.NOTIFY_URL_TRADE,
            "trade_refund":          cls.NOTIFY_URL_TRADE_REFUND,
            "zhima":                 cls.NOTIFY_URL_ZHIMA,
            "merchant_order_sync":   cls.NOTIFY_URL_MERCHANT_ORDER_SYNC,
        }

    @classmethod
    def shouyue_url_resolved(cls) -> str:
        return cls.XINYONG_SHOUYUE_URL.replace("{APP_ID}", cls.app_id() or "PLACEHOLDER_APPID")


# ============================================================================
# 管理后台（独立 namespace）
# ============================================================================
class AdminConfig:
    SESSION_HOURS = 8
    RESTRICT_LAN  = 0
