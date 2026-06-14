# 观澜数码租赁 后端（Python Flask + SQLite）

数据落 SQLite（`app/storage/sqlite_store.py`，每个表 JSON payload），冷启动通过 `app/storage/seed.py` 灌入种子数据。

## 目录结构

```
houdan/
├── requirements.txt
├── run.py                   # 启动入口
├── rsa_keys/                # 支付宝应用私钥 / 支付宝公钥
└── app/
    ├── __init__.py          # Flask 工厂 + ok/fail 响应封装
    ├── alipay_client.py     # 封装 alipay-sdk-python（freeze/unfreeze/certify/order_sync...）
    ├── config.py            # AlipayConfig 等运行时配置
    ├── storage/             # SQLite 持久层（json blob 存 payload）
    └── routes/
        ├── products.py      # 商品
        ├── categories.py    # 分类
        ├── banners.py       # 首页 Banner / 三宫格 / 品牌
        ├── orders.py        # 订单
        ├── user.py          # 用户 + 实名认证
        ├── service.py       # 客服 + FAQ
        ├── alipay.py        # 支付宝芝麻免押 / 实人认证 / 订单同步 / 异步通知
        ├── admin.py         # 商家后台
        └── ...
```

## 启动

```bash
cd houdan
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

默认监听 `http://0.0.0.0:8001`（避开 macOS AirPlay 占用的 5000，及本机其他常用端口）。

## 统一响应格式

```json
{ "code": 0, "msg": "ok", "data": { ... } }
```

`code = 0` 成功，其他为业务错误码。

## 接口清单

### 业务

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/api/banners`                  | 首页 Banner / 三宫格 / 品牌 |
| GET  | `/api/categories`               | 分类列表 |
| GET  | `/api/products?cat_id=1&credit=1&keyword=&page=1&size=20` | 商品列表 |
| GET  | `/api/products/<id>`            | 商品详情 |
| GET  | `/api/orders/tabs`              | 订单状态 Tab |
| GET  | `/api/orders?status=using`      | 订单列表 |
| GET  | `/api/orders/<oid>`             | 订单详情 |
| POST | `/api/orders`                   | 创建订单 `{product_id, days}` |
| POST | `/api/orders/<oid>/cancel`      | 取消/归还订单 |
| GET  | `/api/user/profile`             | 用户信息 |
| GET  | `/api/user/functions`           | "我的"页功能入口 |
| POST | `/api/user/identity`            | 提交实名认证 `{name, phone, id_card}` |
| GET  | `/api/service/info`             | 客服信息（电话+在线入口） |
| GET  | `/api/service/faqs`             | 常见问题 |

### 支付宝芝麻免押

| 方法 | 路径 | 对应支付宝接口 |
|---|---|---|
| POST | `/api/alipay/credit/sign`     | `alipay.user.agreement.page.sign` |
| POST | `/api/alipay/credit/freeze`   | `alipay.fund.auth.order.app.freeze` |
| POST | `/api/alipay/credit/unfreeze` | `alipay.fund.auth.order.unfreeze` |
| POST | `/api/alipay/order/sync`      | `alipay.merchant.order.sync` |

## 支付宝凭证 / 接入清单

- `houdan/rsa_keys/app_private_key.pem`（应用私钥）/ `alipay_public_key.pem`（支付宝公钥）必须落位
- `app/config.py` `AlipayConfig` 配齐 `APP_ID` / `NOTIFY_BASE`（公网 HTTPS）/ `SERVICE_ID` / 类目
- 企业支付宝账户 + 营业执照主体一致
- 类目（category）与 serviceId 一致
- "信用服务守约链接" 配置真实订单详情页 schema
