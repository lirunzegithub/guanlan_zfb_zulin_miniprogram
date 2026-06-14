# 支付宝实名与芝麻免押接口分析

> 基于 IMG_8447 / 8448 / 8449 / 8450 四张截图，逐步还原"确认提交"按钮背后的真实接口链路。

---

## 一、四张截图对应的能力

| 截图 | 现象 | 对应支付宝能力 |
|---|---|---|
| **IMG_8447** | 业务弹窗"当前尚未实名，请前往实名！" + 取消/确定 | **业务前置校验**，不是支付宝接口。读自身后端 `user.verified` 字段，未实名时拦截后续动作 |
| **IMG_8448** | 支付宝原生授权框："验证你提交的身份信息是否与当前支付宝预留信息一致 / 将用于为你提供本应用当前服务" + 拒绝/同意 | **小程序授权 + 用户实名信息共享**：`my.getAuthCode` (scope=`auth_user`) → 后端 `alipay.system.oauth.token` → 后端 `alipay.user.info.share` |
| **IMG_8449** | 标题"蚂蚁云创数字科技（北京）有限公司 身份验证"，提示"获取本次验证过程中拍摄的人脸照片" | **实人认证（人脸识别）**：`alipay.user.certify.open.initialize` → `alipay.user.certify.open.certify` 拿到 certifyUrl → 前端 `my.navigateTo` 进入蚂蚁云创承载页 → 完成后 `alipay.user.certify.open.query` 查结果 |
| **IMG_8450** | "芝麻信用 你的芝麻分已达标 711 / 本单押金 ¥3000.00 已免除 / 租赁期间将自动支付租金 / 物品丢失扣除押金" + 确定 | **芝麻先享 + 信用代扣**：`zhima.credit.payafteruse.creditbizorder.create` 生成签约订单 → `my.tradePay` 唤起原生签约弹窗 → 用户点"确定"完成代扣协议签约 |

---

## 二、"确认提交"按钮的完整接口链路

```
身份信息填写页 → [确认提交]
   │
   ├─① 本地校验（姓名、手机号正则、身份证长度、协议勾选）
   │
   ├─② 客户端：my.getAuthCode({ scopes: ['auth_user'] })
   │     ↓ 弹出 IMG_8448 原生授权框
   │     ↓ 用户点"同意"
   │     拿到 auth_code
   │
   ├─③ POST 自家后端 /api/alipay/identity/verify
   │     入参：{ auth_code, name, id_card }
   │     后端做：
   │        a) alipay.system.oauth.token({ grant_type:'authorization_code', code:auth_code })
   │           → access_token, user_id
   │        b) alipay.user.info.share({ auth_token: access_token })
   │           → 支付宝实名姓名 + 脱敏身份证
   │        c) 后端比对 用户提交 vs 支付宝预留 是否一致
   │        d) 一致：写入数据库；不一致：返回 verify=false
   │
   ├─④ 一致，进入实人认证（可选；高风险租赁建议必做）
   │     POST /api/alipay/certify/init  入参：{ name, id_card }
   │     后端做：
   │        a) alipay.user.certify.open.initialize → certify_id
   │        b) alipay.user.certify.open.certify(certify_id) → certify_url
   │     ↓ 返回 certify_url
   │     ↓ 客户端：my.navigateTo({ url: certify_url })
   │     ↓ 进入 IMG_8449 蚂蚁云创人脸识别页面
   │     ↓ 用户完成活体检测 + 人脸识别，自动跳回
   │
   ├─⑤ 跳回后端：POST /api/alipay/certify/query  入参：{ certify_id }
   │     后端做：alipay.user.certify.open.query(certify_id) → passed=true/false
   │
   └─⑥ passed=true → 业务库写 user.verified=true，跳回上一个业务页
```

---

## 三、用到的支付宝官方接口清单

| 调用方 | 接口名 | 作用 |
|---|---|---|
| 客户端 | `my.getAuthCode` | 弹出授权框（IMG_8448），拿 auth_code |
| 服务端 | `alipay.system.oauth.token` | auth_code → access_token、user_id |
| 服务端 | `alipay.user.info.share` | 拿到用户在支付宝的实名信息（姓名、脱敏身份证、手机号等） |
| 服务端 | `alipay.user.certify.open.initialize` | 创建一笔实人认证 → certify_id |
| 服务端 | `alipay.user.certify.open.certify` | 用 certify_id 换可跳转的 certifyUrl |
| 客户端 | `my.navigateTo(certifyUrl)` 或 `my.startApp` | 进入 IMG_8449 人脸识别页 |
| 服务端 | `alipay.user.certify.open.query` | 查询本次实名认证结果 |

> IMG_8450 的"芝麻信用免押"弹窗不属于实名链路，是后续下单时才走的接口：
> - 服务端 `zhima.credit.payafteruse.creditbizorder.create`（芝麻先享创建订单）或 `alipay.fund.auth.order.app.freeze`（信用预授权冻结）
> - 客户端 `my.tradePay({ tradeNO })` 唤起原生签约/支付弹窗

---

## 四、本项目的后端路由对应表

后端路由在 `app/routes/alipay.py`，全部走 `alipay-sdk-python` 真实调用。

| 后端路由 | 对应支付宝接口 |
|---|---|
| `POST /api/alipay/identity/verify` | `alipay.system.oauth.token` + `alipay.user.info.share` + 业务比对 |
| `POST /api/alipay/certify/init`    | `alipay.user.certify.open.initialize` + `alipay.user.certify.open.certify` |
| `POST /api/alipay/certify/query`   | `alipay.user.certify.open.query` |
| `POST /api/alipay/credit/sign`     | `zhima.credit.payafteruse.creditbizorder.create` + 端内 `my.tradePay` 签约 |
| `POST /api/alipay/credit/freeze`   | `alipay.fund.auth.order.app.freeze` |
| `POST /api/alipay/credit/unfreeze` | `alipay.fund.auth.order.unfreeze` |
| `POST /api/alipay/order/sync`      | `alipay.merchant.order.sync` |

`user.verified` 仅在 `certify/query` 返回 `passed=true` 后写入。
