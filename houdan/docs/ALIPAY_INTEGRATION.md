# 支付宝接口集成说明

> 当前已对接：**alipay.fund.auth.order.app.freeze（创建免押授权订单）** + 查询 + 异步通知验签 +
> `alipay.fund.auth.order.unfreeze`（解冻）+ `alipay.fund.auth.operation.detail.pay`（转支付）+
> `alipay.user.certify.*`（实人认证）+ `alipay.merchant.order.sync`（订单中心）。

## 一、接入凭证准备

1. 安装 SDK（已在 `requirements.txt`）
   ```bash
   pip install -r requirements.txt
   ```
2. 在 [open.alipay.com](https://open.alipay.com) 应用详情页生成密钥对，下载到本地：
   ```
   houdan/rsa_keys/app_private_key.pem      # 应用私钥（自己生成）
   houdan/rsa_keys/alipay_public_key.pem    # 支付宝公钥（控制台下载）
   ```
3. 编辑 `houdan/app/config.py` 的 `AlipayConfig`：
   ```python
   class AlipayConfig:
       ENV        = "prod"            # 或 "sandbox"
       APP_ID     = "2021xxxxxxxxxxxx"
       NOTIFY_BASE = "https://your-domain.com"   # 必须公网 https
       AES_ENCRYPT_KEY = "..."        # 开放平台「接口加密方式」下发的对称密钥
   ```
4. 公网部署 + HTTPS + 域名备案，确保 `NOTIFY_BASE` 下的 notify URL 可达
5. 重启服务，日志出现 `Alipay client = REAL (env=... app_id=...)` 即生效；
   凭证不齐时 `get_client()` 会显式抛 `RuntimeError`（不会静默继续）

## 二、接口契约

### 1. POST `/api/alipay/credit/freeze`

入参：
```json
{
  "out_order_no":   "RTxxxxxxxxxxxxxxxx",    // 商户授权资金订单号（不重复，仅字母数字下划线）
  "out_request_no": "RTxxxxxxxxxxxxxxxx_1",  // 请求流水号（不重复）
  "order_title":    "押金冻结",
  "amount":         3000,
  "scene_code":     "（可选，覆盖 env 默认）",
  "transport_category": "（可选，行业字段）"
}
```

返回：
```json
{
  "code": 0,
  "msg": "freeze 已下发",
  "data": {
    "order_str": "app_id=...&method=alipay.fund.auth.order.app.freeze&biz_content=...&sign=...",
    "out_order_no": "RTxxxxxxxxxxxxxxxx"
  }
}
```

前端拿到 `order_str`：
```javascript
my.tradePay({ orderStr: order_str, success: ..., fail: ... });
```

### 2. POST `/api/alipay/credit/query`

入参：`{ "out_order_no": "RT..." }`
返回：透传 `alipay.fund.auth.operation.detail.query` 的 body 字段。

### 3. POST `/api/alipay/notify/auth_freeze`

支付宝服务器到服务器异步通知。已做：
- `client.verify_notify(params)` 验签
- 验签失败返回 `"fail"`；通过后必须返回纯文本 `"success"`

生产上需要在这里把 `out_order_no` 对应的本地订单状态推进到 `using`，并触发业务的发货流程。

## 三、关键参数对照（支付宝官方文档 → 我们的代码）

| 文档字段 | 类型 | 我们的位置 | 备注 |
|---|---|---|---|
| `out_order_no` | string(64) | freeze 请求体 | 商户授权资金订单号 |
| `out_request_no` | string(64) | freeze 请求体 | 本次操作流水号 |
| `order_title` | string(100) | freeze 请求体 | 订单标题 |
| `amount` | price(11) | freeze 请求体 | 冻结金额（元） |
| `product_code` | string | `AlipayConfig.product_code` | 固定 `PRE_AUTH_ONLINE` |
| `pay_code` | string | `AlipayConfig.pay_code` | 芝麻免押固定 `fp_FreezeInit` |
| `scene_code` | string | `AlipayConfig.scene_code` 或请求覆盖 | 行业场景码，申请后获取 |
| `extra_param` | string(JSON) | 请求体 `transport_category` 等聚合 | 行业自定义字段 |
| `notify_url` | string | `AlipayConfig.notify_url` | 自动塞入请求 |

## 四、异步通知端点清单

线上域名：`https://your-domain.example.com`
配置入口：开放平台 → 我的应用 → 应用详情 → 网关&回调地址。
注意：应用维度只能配 **一个** 全局 NOTIFY_URL（兜底），所以业务调用 SDK 时必须显式
设置 `req.notify_url` 指向以下子路径之一，支付宝会优先使用请求中的 notify_url。

| 端点 | 对应能力 | 业务效果 |
|---|---|---|
| `POST /api/alipay/notify/auth_freeze`   | `alipay.fund.auth.order.app.freeze` / `.order.freeze` | 冻结成功（status=SUCCESS/FROZEN）→ 订单 audit → awaiting_face |
| `POST /api/alipay/notify/auth_unfreeze` | `alipay.fund.auth.order.unfreeze`（operation_type=UNFREEZE） | 解冻成功 → return/overdue/using → done |
| `POST /api/alipay/notify/auth_pay`      | `alipay.fund.auth.operation.detail.pay`（operation_type=PAY） | 预授权转支付成功 → using/overdue → return |
| `POST /api/alipay/notify/trade`         | `alipay.trade.pay` / `alipay.trade.create` 等 | 补差价、续租；trade_status=TRADE_SUCCESS/TRADE_FINISHED 时记录 |
| `POST /api/alipay/notify/trade_refund`  | `alipay.trade.refund` 退款回调 | 退款成功后记录（生产可在此触发资金对账） |
| `POST /api/alipay/notify/zhima`         | 芝麻信用履约 / 退订等回调 | 仅验签 + 记日志，业务按需扩展 |

所有端点的统一规范：

1. **请求体**：`application/x-www-form-urlencoded`，UTF-8；服务端兼容 JSON（仅供调试）
2. **验签**：剔除 `sign` 和 `sign_type` → 剔除空值 → key 字典序拼 `k=v&k=v` → 用支付宝公钥 RSA/RSA2 验签；
   `app/alipay_client.py` 的 `verify_notify` 已实现
3. **幂等**：`app/notify_dedup.py` 用 `notify_id`（兜底 `out_order_no+operation_id` 或 `out_trade_no+trade_no`）做去重；
   生产请换 Redis SETNX 或 DB 唯一索引
4. **响应**：成功 → 纯文本 `success`；任何失败 → 纯文本 `fail`（让支付宝继续重试）
5. **重试节奏**：支付宝在 25h 内最多重试 8 次，间隔 4m / 10m / 10m / 1h / 2h / 6h / 15h
6. **日志**：每条通知都会落到 stderr：`[alipay-notify] ch=auth_freeze verify=True biz=True ...`

### Nginx / 反向代理配置注意点

支付宝服务器到我们的源站要穿过 nginx：

```nginx
location /api/alipay/notify/ {
    # 1) HTTPS：支付宝只调 https://，且必须公网可信证书（Let's Encrypt 即可）
    # 2) 超时：建议给到 30s 以上，notify 处理里可能写 DB / 调外部
    proxy_read_timeout 30s;
    proxy_send_timeout 30s;
    # 3) 透传原始 body 必须保留 Content-Type / Content-Length，不要被 buffer 截断
    proxy_request_buffering on;
    # 4) 不要在 nginx 层加任何 auth_basic / IP 白名单（支付宝出口 IP 不公开，
    #    且会变动），鉴权完全依赖 RSA 签名
    # 5) 把真实客户端 IP 传给 Flask 方便排错
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    proxy_pass http://127.0.0.1:8001;
}
```

- 不要做 IP 白名单（支付宝出口 IP 段未公布，签名就是身份认证）
- 不要 301/302 跳转（支付宝不会跟随）
- 不要返回 5xx / 非 200，否则会被认为失败而重试
- 启用 access_log，与 Flask 的 `[alipay-notify]` 日志交叉对账

## 五、扩展其他接口的步骤

以新接口 X 为例：

1. 在 `app/alipay_client.py` 的 `BaseAlipayClient` 加抽象方法签名
2. `RealAlipayClient` 实现：构造对应 SDK 的 `Request` + `Model`，通过 `self._execute(req, "..._response")` 走签名 + 调用 + code 校验
3. 在 `app/routes/alipay.py` 加 `@bp.post(...)` 调 `get_client().X(...)` 暴露给前端 / 内部使用
4. 如果接口有异步通知：`AlipayConfig` 加 `NOTIFY_URL_X`、SDK 调用前 `req.notify_url = AlipayConfig.NOTIFY_URL_X`，
   在 `routes/alipay.py` 加 `/notify/X` 端点处理（验签 + 幂等 + 业务推进）
