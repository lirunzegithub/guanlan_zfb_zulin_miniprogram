"""支付宝 SDK 封装层。

外部只依赖 `client = get_client()`，再调 `client.auth_freeze_app(...)`。

当前已实现：
- auth_freeze_app   对应 alipay.fund.auth.order.app.freeze
- auth_order_query  对应 alipay.fund.auth.order.query   （回调后查询用）
- verify_notify     异步通知验签
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.config import AlipayConfig

logger = logging.getLogger(__name__)


def _normalize_pay_channels(value) -> str:
    """把简单的渠道码字符串/逗号列表转成阿里要求的 JSON 数组字符串。
    阿里官方要求 enable_pay_channels 是这种格式：
        '[{"payChannelType":"CREDITZHIMA"},{"payChannelType":"PCREDIT_PAY"}]'

    支持输入：
        ""                                → ""（不设字段）
        "CREDITZHIMA"                     → '[{"payChannelType":"CREDITZHIMA"}]'
        "CREDITZHIMA,PCREDIT_PAY"         → '[{"payChannelType":"CREDITZHIMA"},{"payChannelType":"PCREDIT_PAY"}]'
        "[{...}]"（已是 JSON）            → 原样返回
    """
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if s.startswith("["):  # 已经是 JSON 数组字符串，原样用
        return s
    channels = [c.strip() for c in s.split(",") if c.strip()]
    if not channels:
        return ""
    return json.dumps(
        [{"payChannelType": c} for c in channels],
        ensure_ascii=False,
    )


# -----------------------------------------------------------------------------
# 抽象接口
# -----------------------------------------------------------------------------

class BaseAlipayClient:
    # ── 鉴权 / 用户信息 ─────────────────────────────────────────
    def exchange_oauth_token(self, auth_code: str) -> dict:
        """auth_code → {access_token, user_id, expires_in, ...}"""
        raise NotImplementedError

    def user_info_share(self, access_token: str) -> dict:
        """access_token → {user_id, nick_name, avatar, gender, ...}"""
        raise NotImplementedError

    # ── 资金授权（押金/免押）────────────────────────────────────
    def auth_freeze_app(
        self,
        out_order_no: str,
        out_request_no: str,
        order_title: str,
        amount: float,
        product_code: Optional[str] = None,
        scene_code: Optional[str] = None,
        enable_pay_channels: Optional[str] = None,
        extra_param: Optional[dict] = None,
    ) -> dict:
        raise NotImplementedError

    def auth_order_query(self, out_order_no: str,
                         out_request_no: Optional[str] = None) -> dict:
        raise NotImplementedError

    def auth_unfreeze(self, auth_no: str, out_request_no: str,
                      amount: float, remark: str = "") -> dict:
        raise NotImplementedError

    # ── 实名 / 实人认证 ────────────────────────────────────────
    # biz_code 合法取值（官方文档 2026 最新版）：
    #   FACE              多因子人脸认证（默认，小程序/H5/APP 通用）
    #   CERT_PHOTO        多因子证照认证
    #   CERT_PHOTO_FACE   多因子证照 + 人脸
    #   SMART_FACE        多因子快捷认证
    # 历史上的 FACE_ALIPAY_SDK 已被废弃，传它会触发 ILLEGAL_ARGUMENT_FORMAT。
    def certify_init(self, name: str, id_card: str, outer_order_no: str,
                     cert_type: str = "IDENTITY_CARD",
                     biz_code: str = "FACE") -> dict:
        """→ {certify_id}"""
        raise NotImplementedError

    def certify_open(self, certify_id: str) -> dict:
        """→ {certify_url}（小程序场景下可选；前端也能直接 my.startAPVerify(certify_id)）"""
        raise NotImplementedError

    def certify_query(self, certify_id: str) -> dict:
        """→ {passed, fail_reason, identity_info, ...}"""
        raise NotImplementedError

    # ── 芝麻履约 / 商家订单同步 ────────────────────────────────
    def zhima_credit_sign(self, out_agreement_no: str, product_code: str,
                          category: str, biz_no: str,
                          extend_params: Optional[dict] = None) -> dict:
        """→ {agreement_no, sign_str}（端内唤起芝麻签约页）"""
        raise NotImplementedError

    def merchant_order_sync(self, *,
                            out_biz_no: str,
                            buyer_id: str,
                            merchant_order_status: str,
                            order_create_time: str,
                            order_modified_time: str,
                            amount: float,
                            pay_amount: Optional[float] = None,
                            product_name: str = "",
                            product_image_material_id: str = "",
                            item_quantity: str = "1",
                            item_unit_price: Optional[float] = None,
                            business_info: Optional[dict] = None,
                            link_page: str = "",
                            tiny_app_id: Optional[str] = None,
                            biz_type: str = "3C_RENT",
                            category_id: str = "C100845427",
                            notify_url: Optional[str] = None) -> dict:
        """同步订单到支付宝订单中心（alipay.merchant.order.sync）。
        类目 3C_RENT 专用；状态/类目/详情链接全部走 ext_info[OrderExtInfo] 数组。
        """
        raise NotImplementedError

    # ── 小程序码生成（运营分享商品页用）─────────────────────────
    def create_app_qrcode(self, url_param: str, query_param: str = "",
                          describe: str = "", size: str = "m") -> str:
        """alipay.open.app.qrcode.create → 返回小程序码图片 URL。

        url_param   小程序页面路径（如 pages/product/product）
        query_param 进页面的 query（如 id=9&days=7）
        要求小程序已发布上线，否则接口会报"页面不存在/未上线"类错误。
        """
        raise NotImplementedError

    # ── 商品图素材上传（订单中心商品卡需要 material_id）─────────
    def upload_merchant_item_file(self, file_path: str, scene: str = "SYNC_ORDER") -> str:
        """alipay.merchant.item.file.upload → 返回 material_id（专给 merchant.order.sync 用）。

        注意：3C_RENT 类目的订单卡商品图，只认这条接口返回的 material_id。
        早期版本误用了 alipay.offline.material.image.upload，那个返回的 image_id
        阿里收下不报错，但订单中心匹配不上，结果就是订单卡片"无图"。
        """
        raise NotImplementedError

    # ── 预授权转支付（扣款）/ 查询 / 关闭 ────────────────────
    def auth_trade_pay(self, out_trade_no: str, total_amount: float,
                       subject: str, auth_no: str,
                       auth_confirm_mode: str = "NOT_COMPLETE",
                       product_code: str = "PREAUTH_PAY",
                       *,
                       order_id: Optional[str] = None,
                       product_id: Optional[int] = None,
                       product_name: Optional[str] = None,
                       product_image_url: Optional[str] = None,
                       body: Optional[str] = None,
                       service_id: Optional[str] = None,
                       merchant_biz_type: str = "3C_RENT") -> dict:
        raise NotImplementedError

    def trade_create(self, out_trade_no: str, total_amount: float,
                     subject: str, buyer_id: str, body: str = "") -> dict:
        """alipay.trade.create，返回给支付宝小程序 my.tradePay 的 trade_no。"""
        raise NotImplementedError

    def trade_query(self, out_trade_no: Optional[str] = None,
                    trade_no: Optional[str] = None) -> dict:
        raise NotImplementedError

    def trade_close(self, out_trade_no: Optional[str] = None,
                    trade_no: Optional[str] = None,
                    operator_id: str = "") -> dict:
        raise NotImplementedError

    def trade_refund(self, *,
                     refund_amount: float,
                     out_trade_no: Optional[str] = None,
                     trade_no: Optional[str] = None,
                     out_request_no: Optional[str] = None,
                     refund_reason: str = "") -> dict:
        raise NotImplementedError

    def trade_refund_query(self, *,
                           out_request_no: str,
                           out_trade_no: Optional[str] = None,
                           trade_no: Optional[str] = None,
                           query_options: Optional[list] = None) -> dict:
        raise NotImplementedError

    # ── 通知验签 ───────────────────────────────────────────────
    def verify_notify(self, params: dict) -> bool:
        raise NotImplementedError


# -----------------------------------------------------------------------------
# 实现：alipay-sdk-python 官方 SDK
# -----------------------------------------------------------------------------

class RealAlipayClient(BaseAlipayClient):
    def __init__(self) -> None:
        try:
            from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
            from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
        except ImportError as e:
            raise RuntimeError(
                "alipay-sdk-python 未安装：pip install alipay-sdk-python"
            ) from e

        cfg = AlipayClientConfig()
        cfg.server_url = AlipayConfig.gateway()
        cfg.app_id = AlipayConfig.app_id()
        cfg.app_private_key = AlipayConfig.app_private_key()
        cfg.alipay_public_key = AlipayConfig.alipay_public_key()
        cfg.sign_type = AlipayConfig.SIGN_TYPE
        # AES 接口内容加密：开放平台「接口加密方式」配置后，SDK 会自动对需加密的字段加解密
        if AlipayConfig.AES_ENCRYPT_KEY:
            cfg.encrypt_key = AlipayConfig.AES_ENCRYPT_KEY
        self._client = DefaultAlipayClient(alipay_client_config=cfg, logger=logger)

    # 内部：execute → 直接拿 dict response body；非 10000 抛 RuntimeError
    def _execute(self, req, resp_key: str) -> dict:
        raw = self._client.execute(req)
        body = json.loads(raw) if isinstance(raw, str) else raw
        # alipay 标准响应外层包 `<method>_response`
        payload = body.get(resp_key) if isinstance(body, dict) else None
        if not isinstance(payload, dict):
            payload = body if isinstance(body, dict) else {"raw": raw}
        code = str(payload.get("code") or "")
        if code and code != "10000":
            raise RuntimeError(
                f"alipay {resp_key} 失败: code={code} msg={payload.get('msg')} "
                f"sub_code={payload.get('sub_code')} sub_msg={payload.get('sub_msg')}"
            )
        return payload

    # ------- OAuth: auth_code → access_token / user_id -------
    def exchange_oauth_token(self, auth_code):
        from alipay.aop.api.request.AlipaySystemOauthTokenRequest import (
            AlipaySystemOauthTokenRequest,
        )
        req = AlipaySystemOauthTokenRequest()
        req.grant_type = "authorization_code"
        req.code = auth_code
        body = self._execute(req, "alipay_system_oauth_token_response")
        return {
            "access_token": body.get("access_token", ""),
            "user_id":      body.get("user_id", ""),
            "expires_in":   int(body.get("expires_in") or 0),
            "re_expires_in": int(body.get("re_expires_in") or 0),
            "refresh_token": body.get("refresh_token", ""),
        }

    # ------- 用户信息（auth_user scope）-------
    def user_info_share(self, access_token):
        from alipay.aop.api.request.AlipayUserInfoShareRequest import (
            AlipayUserInfoShareRequest,
        )
        req = AlipayUserInfoShareRequest()
        # auth_token 走运行时参数而不是 biz_content
        raw = self._client.execute(req, access_token)
        body = json.loads(raw) if isinstance(raw, str) else raw
        payload = body.get("alipay_user_info_share_response") if isinstance(body, dict) else None
        if not isinstance(payload, dict):
            payload = body if isinstance(body, dict) else {"raw": raw}
        code = str(payload.get("code") or "")
        if code and code != "10000":
            raise RuntimeError(
                f"alipay user_info_share 失败: code={code} msg={payload.get('msg')} "
                f"sub_code={payload.get('sub_code')} sub_msg={payload.get('sub_msg')}"
            )
        return {
            "user_id":   payload.get("user_id", ""),
            "nick_name": payload.get("nick_name", ""),
            "avatar":    payload.get("avatar", ""),
            "gender":    payload.get("gender", ""),
            "province":  payload.get("province", ""),
            "city":      payload.get("city", ""),
        }

    # ------- 创建免押授权（app freeze）-------
    def auth_freeze_app(self, out_order_no, out_request_no, order_title, amount,
                        product_code=None, scene_code=None, enable_pay_channels=None, extra_param=None):
        from alipay.aop.api.request.AlipayFundAuthOrderAppFreezeRequest import (
            AlipayFundAuthOrderAppFreezeRequest,
        )
        from alipay.aop.api.domain.AlipayFundAuthOrderAppFreezeModel import (
            AlipayFundAuthOrderAppFreezeModel,
        )

        model = AlipayFundAuthOrderAppFreezeModel()
        model.out_order_no = out_order_no
        model.out_request_no = out_request_no
        model.order_title = order_title
        model.amount = str(amount)                 # SDK 要求字符串
        model.product_code = product_code or AlipayConfig.PRODUCT_CODE
        # enable_pay_channels 实际是 JSON 数组字符串：'[{"payChannelType":"CREDITZHIMA"}]'
        # 不能传裸渠道码，否则阿里端"支付渠道格式非法"→ my.tradePay 返回 6001
        # None/空串 → 不设字段，让支付宝按用户实际能力自动选渠道（走普通押金）
        normalized_channels = _normalize_pay_channels(enable_pay_channels)
        if normalized_channels:
            model.enable_pay_channels = normalized_channels
        if scene_code:
            model.scene_code = scene_code

        # 信用借还/信用免押预授权必传两个 extra_param 字段：
        #   serviceId  —— 开放平台「信用借还」产品申请到的服务 ID
        #   category   —— 业务类目（如 RENT_3C / RENT_DIGITAL），告诉阿里这是什么业务
        # 任一字段缺失，阿里都会把请求降级为普通预授权（用户看到选择付款方式页，
        # 而不是图中那张「芝麻信用 | 免押」授权页）。
        merged_extra = dict(extra_param or {})
        if AlipayConfig.service_id() and "serviceId" not in merged_extra:
            merged_extra["serviceId"] = AlipayConfig.service_id()
        if AlipayConfig.scene_code() and "category" not in merged_extra:
            merged_extra["category"] = AlipayConfig.scene_code()
        if merged_extra:
            model.extra_param = json.dumps(merged_extra, ensure_ascii=False)

        req = AlipayFundAuthOrderAppFreezeRequest(biz_model=model)
        req.notify_url = AlipayConfig.notify_url(AlipayConfig.NOTIFY_PATH_AUTH_FREEZE)

        # sdkExecute 在 Python SDK 里叫 sdk_execute，返回拼好的 orderStr
        order_str = self._client.sdk_execute(req)
        return {
            "order_str": order_str,
            "out_order_no": out_order_no,
        }

    # ------- 预授权转支付（扣款）alipay.trade.pay -------

    def trade_create(self, out_trade_no, total_amount, subject, buyer_id, body=""):
        """支付宝小程序收款：服务端创建交易，小程序端用 tradeNO 拉起收银台。

        不得换回 alipay.trade.app.pay / QUICK_MSECURITY_PAY：那是独立 App
        支付产品，小程序应用未签约时会被产品权限拦截。
        """
        from alipay.aop.api.request.AlipayTradeCreateRequest import AlipayTradeCreateRequest
        from alipay.aop.api.domain.AlipayTradeCreateModel import AlipayTradeCreateModel

        model = AlipayTradeCreateModel()
        model.out_trade_no = out_trade_no
        model.total_amount = f"{float(total_amount):.2f}"
        model.subject = subject
        model.buyer_id = buyer_id
        if body:
            model.body = body
        req = AlipayTradeCreateRequest(biz_model=model)
        req.notify_url = AlipayConfig.notify_url(AlipayConfig.NOTIFY_PATH_TRADE)
        try:
            resp = self._execute(req, "alipay_trade_create_response")
        except RuntimeError as create_err:
            # 重复点击、或从旧 App 支付实现切换过来时，同一
            # out_trade_no 可能已在支付宝生成了待支付交易。主动查询并
            # 复用它的 trade_no，避免让用户删单重下。
            try:
                existing = self.trade_query(out_trade_no=out_trade_no)
                if (existing.get("trade_no") or "").strip():
                    resp = existing
                else:
                    raise create_err
            except Exception:
                raise create_err
        trade_no = (resp.get("trade_no") or "").strip()
        if not trade_no:
            raise RuntimeError("alipay.trade.create 成功响应缺少 trade_no")
        return {"trade_no": trade_no, "out_trade_no": out_trade_no}

    # 信用免押产品下用 auth_no（freeze 时阿里返回的支付宝授权号）调用此接口
    # 把冻结额度里的部分转成实际支付。auth_confirm_mode:
    #   COMPLETE     —— 本次扣款后自动解冻剩余冻结金额（最后一笔用）
    #   NOT_COMPLETE —— 本次扣款后继续冻结剩余（中间扣款用，默认）
    def auth_trade_pay(self, out_trade_no, total_amount, subject, auth_no,
                       auth_confirm_mode="NOT_COMPLETE",
                       product_code="PREAUTH_PAY",
                       *,
                       order_id=None,
                       product_id=None,
                       product_name=None,
                       product_image_url=None,
                       body=None,
                       service_id=None,
                       merchant_biz_type="3C_RENT"):
        """预授权扣款。

        除了核心扣款字段外，可选传入商品/订单上下文，用于把账单详情页渲染成
        服务卡片（带商品图、商品名、跳回小程序订单详情）：

          order_id            关联的本地订单号（= merchant.order.sync 的 out_biz_no）
          product_id          商品 id
          product_name        商品名（也用作 goods_detail.goods_name）
          product_image_url   商品主图绝对 URL（goods_detail.show_url 渲染商品图）
          body                扣款说明长文（账单卡副标题，optional）
          service_id          芝麻履约 / 账单卡服务 id（来自 AlipayConfig.SERVICE_ID）
          merchant_biz_type   业务类型常量，与订单中心 sync 保持一致（默认 3C_RENT）

        以上字段任一缺失，对应字段就不发；最坏退化等价于"只发 subject + 金额"的旧行为。
        """
        from alipay.aop.api.request.AlipayTradePayRequest import AlipayTradePayRequest
        from alipay.aop.api.domain.AlipayTradePayModel import AlipayTradePayModel
        from alipay.aop.api.domain.GoodsDetail import GoodsDetail

        model = AlipayTradePayModel()
        model.out_trade_no = out_trade_no
        model.total_amount = f"{float(total_amount):.2f}"
        model.subject = subject
        model.auth_no = auth_no
        model.auth_confirm_mode = auth_confirm_mode
        model.product_code = product_code
        if body:
            model.body = body

        # ── goods_detail：账单详情页用 show_url 渲染商品图 ──
        # 没有商品上下文就不传，避免把 subject 重复一遍误导
        if product_id or product_name or product_image_url:
            gd = GoodsDetail()
            gd.goods_id = str(product_id or out_trade_no)
            gd.goods_name = product_name or subject
            gd.quantity = 1
            gd.price = f"{float(total_amount):.2f}"
            if product_image_url:
                gd.show_url = product_image_url
            model.goods_detail = [gd]

        # ── business_params：JSON 字符串 ──
        # service_id：声明这笔扣款挂在哪条服务模板下，是账单卡渲染的关键
        # out_biz_no：链接到已经 sync 过的订单中心订单，账单卡可跳回小程序订单详情
        # merchant_biz_type：与订单中心保持一致，便于阿里端 join 数据
        biz_params = {}
        if service_id:
            biz_params["service_id"] = service_id
        if order_id:
            biz_params["out_biz_no"] = order_id
        if merchant_biz_type:
            biz_params["merchant_biz_type"] = merchant_biz_type
        if biz_params:
            model.business_params = json.dumps(biz_params, ensure_ascii=False)

        req = AlipayTradePayRequest(biz_model=model)
        body_resp = self._execute(req, "alipay_trade_pay_response")
        return body_resp

    # ------- 查询单笔扣款 alipay.trade.query -------
    def trade_query(self, out_trade_no=None, trade_no=None):
        from alipay.aop.api.request.AlipayTradeQueryRequest import AlipayTradeQueryRequest
        from alipay.aop.api.domain.AlipayTradeQueryModel import AlipayTradeQueryModel

        model = AlipayTradeQueryModel()
        if out_trade_no: model.out_trade_no = out_trade_no
        if trade_no:     model.trade_no = trade_no
        req = AlipayTradeQueryRequest(biz_model=model)
        resp_str = self._client.execute(req)
        resp = json.loads(resp_str) if isinstance(resp_str, str) else resp_str
        body = resp.get("alipay_trade_query_response", resp)
        return body

    # ------- 关闭/取消扣款 alipay.trade.close -------
    # 仅 WAIT_BUYER_PAY / INIT 状态可关，TRADE_SUCCESS 等已成功状态需走退款流程
    def trade_close(self, out_trade_no=None, trade_no=None, operator_id=""):
        from alipay.aop.api.request.AlipayTradeCloseRequest import AlipayTradeCloseRequest
        from alipay.aop.api.domain.AlipayTradeCloseModel import AlipayTradeCloseModel

        model = AlipayTradeCloseModel()
        if out_trade_no: model.out_trade_no = out_trade_no
        if trade_no:     model.trade_no = trade_no
        if operator_id:  model.operator_id = operator_id
        req = AlipayTradeCloseRequest(biz_model=model)
        resp_str = self._client.execute(req)
        resp = json.loads(resp_str) if isinstance(resp_str, str) else resp_str
        body = resp.get("alipay_trade_close_response", resp)
        return body

    # ------- 退款 alipay.trade.refund -------
    # 支持多次部分退款；同一交易的多笔退款必须用不同 out_request_no，
    # 重试同一笔退款时务必复用相同 out_request_no 以保证幂等。
    # 注：code=10000 仅表示请求受理成功，fund_change=Y 才代表资金已退；
    # fund_change=N 时调用方应走 trade_refund_query 兜底确认最终状态。
    def trade_refund(self, *, refund_amount, out_trade_no=None, trade_no=None,
                     out_request_no=None, refund_reason=""):
        from alipay.aop.api.request.AlipayTradeRefundRequest import AlipayTradeRefundRequest
        from alipay.aop.api.domain.AlipayTradeRefundModel import AlipayTradeRefundModel

        model = AlipayTradeRefundModel()
        model.refund_amount = str(refund_amount)
        if out_trade_no:   model.out_trade_no = out_trade_no
        if trade_no:       model.trade_no = trade_no
        if out_request_no: model.out_request_no = out_request_no
        if refund_reason:  model.refund_reason = refund_reason
        req = AlipayTradeRefundRequest(biz_model=model)
        req.notify_url = AlipayConfig.notify_url(AlipayConfig.NOTIFY_PATH_TRADE_REFUND)
        resp_str = self._client.execute(req)
        resp = json.loads(resp_str) if isinstance(resp_str, str) else resp_str
        body = resp.get("alipay_trade_refund_response", resp)
        return body

    # ------- 查询退款 alipay.trade.fastpay.refund.query -------
    # 必传 out_request_no（与发起退款时一致），同时配 out_trade_no 或 trade_no 二选一。
    # refund_status == "REFUND_SUCCESS" 才代表退款实际成功；未返回该字段表示未成功。
    def trade_refund_query(self, *, out_request_no, out_trade_no=None,
                           trade_no=None, query_options=None):
        from alipay.aop.api.request.AlipayTradeFastpayRefundQueryRequest import (
            AlipayTradeFastpayRefundQueryRequest,
        )
        from alipay.aop.api.domain.AlipayTradeFastpayRefundQueryModel import (
            AlipayTradeFastpayRefundQueryModel,
        )

        model = AlipayTradeFastpayRefundQueryModel()
        model.out_request_no = out_request_no
        if out_trade_no:   model.out_trade_no = out_trade_no
        if trade_no:       model.trade_no = trade_no
        if query_options:  model.query_options = list(query_options)
        req = AlipayTradeFastpayRefundQueryRequest(biz_model=model)
        resp_str = self._client.execute(req)
        resp = json.loads(resp_str) if isinstance(resp_str, str) else resp_str
        body = resp.get("alipay_trade_fastpay_refund_query_response", resp)
        return body

    # ------- 查询授权订单 -------
    # 新版 alipay-sdk-python 已移除 AlipayFundAuthOrderQueryRequest 类，
    # 统一改走 alipay.fund.auth.operation.detail.query（detail_query）来查授权状态。
    # 该接口要求 (out_order_no + out_request_no) 配对；out_request_no 在 freeze 时
    # 已被写到订单表的 alipay_out_request_no 字段，这里自动读出来用。
    def auth_order_query(self, out_order_no, out_request_no=None):
        if not out_request_no:
            try:
                from app.storage.repos import order_repo
                o = order_repo.get(out_order_no)
                if o:
                    out_request_no = (o.get("alipay_out_request_no") or "").strip()
            except Exception:
                pass
        if not out_request_no:
            return {
                "found": False,
                "out_order_no": out_order_no,
                "reason": "缺少 out_request_no，无法查询授权订单状态",
            }

        detail = self.auth_operation_detail_query(
            out_order_no=out_order_no,
            out_request_no=out_request_no,
            operation_type="FREEZE",
        )

        # 字段语义映射，保持调用方（credit_query / transition_freeze_done）原有判断习惯：
        #   旧 status (订单整体状态) ← order_status (新版 INIT/AUTHORIZED/FINISH/CLOSED)
        #   旧 payment_method (实际渠道) ← 由 pre_auth_type 推断：
        #     - is_credit_auth=True → "CREDITZHIMA"
        #     - 否则                  → "OTHER"
        return {
            "found":          detail.get("found", False),
            "out_order_no":   detail.get("out_order_no") or out_order_no,
            "auth_no":        detail.get("auth_no") or "",
            "status":         detail.get("order_status") or "",
            "amount":         detail.get("amount") or detail.get("total_freeze_amount") or "",
            "payment_method": "CREDITZHIMA" if detail.get("is_credit_auth") else "OTHER",
            "code":           detail.get("code") or "",
            "msg":            detail.get("msg") or "",
            "sub_code":       detail.get("sub_code") or "",
            "sub_msg":        detail.get("sub_msg") or "",
            "_raw":           detail,
        }

    # ------- 查询资金授权操作明细（alipay.fund.auth.operation.detail.query）-------
    # 必须配对参数：(out_order_no + out_request_no) 或 (auth_no + operation_id)
    # operation_type: FREEZE（默认）/ UNFREEZE / PAY
    def auth_operation_detail_query(self, out_order_no=None, out_request_no=None,
                                    auth_no=None, operation_id=None,
                                    operation_type="FREEZE"):
        from alipay.aop.api.request.AlipayFundAuthOperationDetailQueryRequest import (
            AlipayFundAuthOperationDetailQueryRequest,
        )
        from alipay.aop.api.domain.AlipayFundAuthOperationDetailQueryModel import (
            AlipayFundAuthOperationDetailQueryModel,
        )
        model = AlipayFundAuthOperationDetailQueryModel()
        if out_order_no:    model.out_order_no = out_order_no
        if out_request_no:  model.out_request_no = out_request_no
        if auth_no:         model.auth_no = auth_no
        if operation_id:    model.operation_id = operation_id
        if operation_type:  model.operation_type = operation_type

        req = AlipayFundAuthOperationDetailQueryRequest(biz_model=model)
        resp_str = self._client.execute(req)
        resp = json.loads(resp_str) if isinstance(resp_str, str) else resp_str
        body = resp.get("alipay_fund_auth_operation_detail_query_response", resp)
        # 不抛错，由调用方根据 code 判断；pre_auth_type=CREDIT_AUTH 即芝麻信用免押
        return {
            "found": body.get("code") == "10000",
            "is_credit_auth": body.get("pre_auth_type") == "CREDIT_AUTH",
            **body,
        }

    # ------- 解冻预授权 -------
    def auth_unfreeze(self, auth_no, out_request_no, amount, remark=""):
        from alipay.aop.api.request.AlipayFundAuthOrderUnfreezeRequest import (
            AlipayFundAuthOrderUnfreezeRequest,
        )
        from alipay.aop.api.domain.AlipayFundAuthOrderUnfreezeModel import (
            AlipayFundAuthOrderUnfreezeModel,
        )
        model = AlipayFundAuthOrderUnfreezeModel()
        model.auth_no = auth_no
        model.out_request_no = out_request_no
        model.amount = str(amount)
        if remark:
            model.remark = remark
        req = AlipayFundAuthOrderUnfreezeRequest(biz_model=model)
        req.notify_url = AlipayConfig.notify_url(AlipayConfig.NOTIFY_PATH_AUTH_UNFREEZE)
        body = self._execute(req, "alipay_fund_auth_order_unfreeze_response")
        return {
            "auth_no": body.get("auth_no") or auth_no,
            "out_request_no": body.get("out_request_no") or out_request_no,
            "status": body.get("status") or "SUCCESS",
            **body,
        }

    # ------- 实人认证（init / open / query 三段式） -------
    def certify_init(self, name, id_card, outer_order_no,
                     cert_type="IDENTITY_CARD", biz_code="FACE"):
        from alipay.aop.api.request.AlipayUserCertifyOpenInitializeRequest import (
            AlipayUserCertifyOpenInitializeRequest,
        )
        from alipay.aop.api.domain.AlipayUserCertifyOpenInitializeModel import (
            AlipayUserCertifyOpenInitializeModel,
        )
        # SDK 3.6+ 把 IdentityParam / MerchantConfig 改名为 OpenCertify* 系列
        from alipay.aop.api.domain.OpenCertifyIdentityParam import OpenCertifyIdentityParam
        from alipay.aop.api.domain.OpenCertifyMerchantConfig import OpenCertifyMerchantConfig

        ident = OpenCertifyIdentityParam()
        ident.identity_type = "CERT_INFO"
        ident.cert_type = cert_type
        ident.cert_name = name
        ident.cert_no = id_card

        # merchant_config 字段（按官方 Java 示例对齐）：
        #   return_url:            必填，合法 https URL；小程序场景实际不会跳转，仅做格式校验
        #   face_reserve_strategy: "reserve" 保留人脸照片（用于后续复用） / "never" 不保留
        merchant_cfg = OpenCertifyMerchantConfig()
        merchant_cfg.return_url = AlipayConfig.notify_url(AlipayConfig.CERTIFY_RETURN_PATH)
        merchant_cfg.face_reserve_strategy = "reserve"

        model = AlipayUserCertifyOpenInitializeModel()
        model.outer_order_no = outer_order_no
        model.biz_code = biz_code
        model.identity_param = ident
        model.merchant_config = merchant_cfg

        req = AlipayUserCertifyOpenInitializeRequest(biz_model=model)
        body = self._execute(req, "alipay_user_certify_open_initialize_response")
        return {"certify_id": body.get("certify_id") or ""}

    def certify_open(self, certify_id):
        from alipay.aop.api.request.AlipayUserCertifyOpenCertifyRequest import (
            AlipayUserCertifyOpenCertifyRequest,
        )
        from alipay.aop.api.domain.AlipayUserCertifyOpenCertifyModel import (
            AlipayUserCertifyOpenCertifyModel,
        )
        model = AlipayUserCertifyOpenCertifyModel()
        model.certify_id = certify_id
        req = AlipayUserCertifyOpenCertifyRequest(biz_model=model)
        # certify 走 page execute（返回的是可端内直接 navigateTo 的 url）
        certify_url = self._client.page_execute(req, "GET")
        return {"certify_id": certify_id, "certify_url": certify_url}

    def certify_query(self, certify_id):
        from alipay.aop.api.request.AlipayUserCertifyOpenQueryRequest import (
            AlipayUserCertifyOpenQueryRequest,
        )
        from alipay.aop.api.domain.AlipayUserCertifyOpenQueryModel import (
            AlipayUserCertifyOpenQueryModel,
        )
        model = AlipayUserCertifyOpenQueryModel()
        model.certify_id = certify_id
        req = AlipayUserCertifyOpenQueryRequest(biz_model=model)
        body = self._execute(req, "alipay_user_certify_open_query_response")
        passed = (body.get("passed") or "").upper() == "T"
        return {
            "certify_id": certify_id,
            "passed": passed,
            "fail_reason": body.get("fail_reason") or "",
            "identity_info": body.get("identity_info") or {},
        }

    # ------- 芝麻履约签约 -------
    def zhima_credit_sign(self, out_agreement_no, product_code,
                          category, biz_no, extend_params=None):
        from alipay.aop.api.request.ZhimaCreditPayafteruseCreditbizorderOrderRequest import (
            ZhimaCreditPayafteruseCreditbizorderOrderRequest,
        )
        from alipay.aop.api.domain.ZhimaCreditPayafteruseCreditbizorderOrderModel import (
            ZhimaCreditPayafteruseCreditbizorderOrderModel,
        )
        model = ZhimaCreditPayafteruseCreditbizorderOrderModel()
        model.out_agreement_no = out_agreement_no
        model.product_code = product_code           # 由芝麻签约后下发
        model.category = category                   # 如 RENT_3C / RENT_DIGITAL
        model.biz_no = biz_no                       # 商户自定义业务号
        if extend_params:
            model.extend_params = json.dumps(extend_params, ensure_ascii=False)

        req = ZhimaCreditPayafteruseCreditbizorderOrderRequest(biz_model=model)
        body = self._execute(req, "zhima_credit_payafteruse_creditbizorder_order_response")
        return {
            "agreement_no": body.get("biz_no") or body.get("agreement_no") or "",
            **body,
        }

    # ------- 小程序码生成 -------
    # 接口：alipay.open.app.qrcode.create
    # 返回 qr_code_url：扫码（支付宝扫一扫）打开小程序 url_param 页 + query_param
    def create_app_qrcode(self, url_param, query_param="", describe="", size="m"):
        from alipay.aop.api.request.AlipayOpenAppQrcodeCreateRequest import (
            AlipayOpenAppQrcodeCreateRequest,
        )
        from alipay.aop.api.domain.AlipayOpenAppQrcodeCreateModel import (
            AlipayOpenAppQrcodeCreateModel,
        )
        model = AlipayOpenAppQrcodeCreateModel()
        model.url_param = url_param
        if query_param:
            model.query_param = query_param
        model.describe = describe or "商品分享"
        model.size = size
        req = AlipayOpenAppQrcodeCreateRequest(biz_model=model)
        body = self._execute(req, "alipay_open_app_qrcode_create_response")
        url = (body.get("qr_code_url") or "").strip()
        if not url:
            raise RuntimeError(f"小程序码生成成功但响应无 qr_code_url：{body}")
        return url

    # ------- 商品图素材上传（订单中心商品卡片图）-------
    # 接口：alipay.merchant.item.file.upload（"上传商品文件"）
    # 入参：scene（业务场景，3C_RENT 订单同步用 SYNC_ORDER）/ file_content（FileItem）
    # 返回：material_id（即 sync.item_order_list[].ext_info[image_material_id]）
    # 注意：SDK 的 file_content 字段 setter 只接 FileItem，普通 bytes 会被静默丢掉
    def upload_merchant_item_file(self, file_path, scene="SYNC_ORDER"):
        from alipay.aop.api.request.AlipayMerchantItemFileUploadRequest import (
            AlipayMerchantItemFileUploadRequest,
        )
        from alipay.aop.api.FileItem import FileItem
        import os as _os

        if not file_path or not _os.path.exists(file_path):
            raise RuntimeError(f"素材文件不存在：{file_path}")

        ext = _os.path.splitext(file_path)[1].lstrip(".").lower() or "jpg"
        if ext == "jpeg":
            ext = "jpg"
        if ext not in ("jpg", "png", "gif", "bmp"):
            raise RuntimeError(f"不支持的图片格式：{ext}（仅支持 jpg/png/gif/bmp）")

        with open(file_path, "rb") as f:
            content = f.read()

        req = AlipayMerchantItemFileUploadRequest()
        req.scene = scene
        req.file_content = FileItem(
            file_name=_os.path.basename(file_path),
            file_content=content,
        )
        body = self._execute(req, "alipay_merchant_item_file_upload_response")
        material_id = (body.get("material_id") or "").strip()
        if not material_id:
            raise RuntimeError(f"上传成功但响应里无 material_id：{body}")
        return material_id

    # ------- 商家订单履约状态同步 -------
    # 对应 alipay.merchant.order.sync，类目 3C_RENT（线上租赁）。
    # 协议要点（详见 docs/ORDER_CENTER_SYNC.md）：
    #   1. 顶层字段只有 out_biz_no / buyer_id / order_type / 时间字段 / amount / item_order_list / ext_info
    #   2. 状态/类目/详情链接/business_info 全部塞 ext_info 数组（OrderExtInfo 对象）
    #   3. item_order_list 必填且每个商品要带 image_material_id（占位先用空串）
    #   4. 3C_RENT 类目不用 logistics_info_list；物流单号塞 business_info.courier_number
    def merchant_order_sync(self, *,
                            out_biz_no,
                            buyer_id,
                            merchant_order_status,
                            order_create_time,
                            order_modified_time,
                            amount,
                            pay_amount=None,
                            product_name="",
                            product_image_material_id="",
                            item_quantity="1",
                            item_unit_price=None,
                            business_info=None,
                            link_page="",
                            tiny_app_id=None,
                            biz_type="3C_RENT",
                            category_id="C100845427",
                            notify_url=None):
        from alipay.aop.api.request.AlipayMerchantOrderSyncRequest import (
            AlipayMerchantOrderSyncRequest,
        )
        from alipay.aop.api.domain.AlipayMerchantOrderSyncModel import (
            AlipayMerchantOrderSyncModel,
        )
        from alipay.aop.api.domain.OrderExtInfo import OrderExtInfo
        from alipay.aop.api.domain.ItemOrderInfo import ItemOrderInfo

        def _ext(k, v):
            e = OrderExtInfo()
            e.ext_key = k
            e.ext_value = "" if v is None else str(v)
            return e

        model = AlipayMerchantOrderSyncModel()
        model.out_biz_no = out_biz_no
        model.buyer_id = buyer_id
        model.order_type = "SERVICE_ORDER"
        model.order_create_time = order_create_time
        model.order_modified_time = order_modified_time
        model.amount = f"{float(amount):.2f}"
        if pay_amount is not None:
            model.pay_amount = f"{float(pay_amount):.2f}"
        if category_id and hasattr(model, "category_id"):
            model.category_id = category_id

        # ── item_order_list（商品信息列表）──
        item_ext = _ext("image_material_id", product_image_material_id or "")
        item = ItemOrderInfo()
        item.item_name = product_name or "租赁商品"
        # quantity / unit_price 成对：传了就一起传
        if item_unit_price is not None:
            item.quantity = str(item_quantity)
            item.unit_price = f"{float(item_unit_price):.2f}"
        item.ext_info = [item_ext]
        model.item_order_list = [item]

        # ── 订单扩展字段（状态/类目/详情链接/appid/business_info）──
        biz_json = json.dumps(business_info or {}, ensure_ascii=False)
        model.ext_info = [
            _ext("merchant_order_status",    merchant_order_status),
            _ext("merchant_biz_type",        biz_type),
            _ext("merchant_order_link_page", link_page or "/pages/order-detail/order-detail"),
            _ext("tiny_app_id",              tiny_app_id or AlipayConfig.app_id()),
            _ext("business_info",            biz_json),
        ]

        req = AlipayMerchantOrderSyncRequest(biz_model=model)
        if notify_url:
            req.notify_url = notify_url
        body = self._execute(req, "alipay_merchant_order_sync_response")
        return {"out_biz_no": out_biz_no, "status": merchant_order_status, **body}

    # ------- 异步通知验签 -------
    def verify_notify(self, params: dict) -> bool:
        """支付宝异步通知验签（官方规范）。

        规则（见 https://opendocs.alipay.com/open/200/106120）：
          1. 剔除 `sign` 和 `sign_type` 两个字段
          2. 剔除 value 为空字符串的字段（None 也算空）
          3. 剩余参数按 key 字典序升序排列
          4. 拼接成 `k1=v1&k2=v2&...&kn=vn`（value 保持原样，不做 URL 编码）
          5. 用支付宝公钥按 `sign_type` 指定算法（RSA=SHA-1 / RSA2=SHA-256）验签

        rsa 库的 `verify` 会按 signature 长度自动识别 SHA-1 / SHA-256，
        所以这里不需要根据 sign_type 显式分支。
        """
        from alipay.aop.api.util.SignatureUtils import verify_with_rsa

        # 复制一份，避免污染调用方字典（caller 还要打日志）
        local = dict(params)
        sign = local.pop("sign", "")
        local.pop("sign_type", None)
        if not sign:
            logger.warning("notify verify: missing sign")
            return False

        # 按 key 字典序，剔除空 value
        items = sorted((k, v) for k, v in local.items() if v not in (None, ""))
        signed = "&".join(f"{k}={v}" for k, v in items)

        try:
            return bool(verify_with_rsa(
                AlipayConfig.alipay_public_key(),
                signed.encode("utf-8"),
                sign,
            ))
        except Exception as e:
            logger.warning("notify verify failed: %s | content=%s", e, signed[:200])
            return False


# -----------------------------------------------------------------------------
# 工厂
# -----------------------------------------------------------------------------

_client: Optional[BaseAlipayClient] = None


def get_client() -> BaseAlipayClient:
    """惰性构造真实客户端；未配置就绪时显式抛错。"""
    global _client
    if _client is not None:
        return _client

    ready, reason = AlipayConfig.is_real_ready()
    if not ready:
        raise RuntimeError(f"AlipayClient 未就绪：{reason}（请检查 APP_ID / 私钥 / 公钥配置）")

    _client = RealAlipayClient()
    logger.info("Alipay client = REAL (env=%s app_id=%s)", AlipayConfig.ENV, AlipayConfig.app_id())
    return _client


def reset_client() -> None:
    """让下次 get_client() 用最新配置重建（settings.json 改了 alipay_app_id 后调）。"""
    global _client
    _client = None
