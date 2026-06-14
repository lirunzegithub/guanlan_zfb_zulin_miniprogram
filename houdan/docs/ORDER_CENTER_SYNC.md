# 订单中心对接方案（alipay.merchant.order.sync · 类目 3C_RENT）

> 把本站租赁订单同步到「支付宝 → 我的 → 全部订单」里展示。
>
> 类目：**线上租赁** `merchant_biz_type = 3C_RENT`
>
> 文档：https://opendocs.alipay.com/solution/0de1h8

---

## 一、协议结构（项目当前实现需要重写）

### 1.1 接口的真实参数模型

`alipay.merchant.order.sync` 的 model 字段：

| 顶层字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `out_biz_no` | String | ✅ | 外部订单号（同一订单后续更新需用同一值） |
| `buyer_id` 或 `buyer_open_id` | String | ✅ | 支付宝 2088 / open_id（新商户推荐 open_id） |
| `order_type` | String | ✅ | 固定 `SERVICE_ORDER` |
| `order_create_time` | String | ✅ | `yyyy-MM-dd HH:mm:ss` |
| `order_modified_time` | String | ✅ | `yyyy-MM-dd HH:mm:ss.SSS`（**毫秒精度**，用于乱序控制） |
| `amount` | Price | 建议传 | 订单总金额，元，2 位小数 |
| `pay_amount` | Price | 建议传 | 实付金额 |
| `discount_amount` | Price | 否 | 优惠金额（带 `discount_info_list` 时必填） |
| `item_order_list` | List | ✅ | 商品信息列表（含商品图、商品名）|
| `ext_info` | **List of OrderExtInfo** | ✅ | **状态/类型/详情链接全部在这里** |
| `trade_no` | String | 否 | 支付宝交易号（带了就要一直带） |
| `service_code` | String | 否 | 服务提报后获得的 service_id（关联订单与服务） |
| `category_id` | String | 否 | `C100845427`（本类目固定值） |
| `source_app` | String | 否 | 默认 `Alipay` |

> ⚠️ **没有 `status` / `biz_type` / `logistics_info_list` 这些顶层字段** —— 项目当前 `alipay_client.py:merchant_order_sync` 把它们当顶层字段直传是错的。

### 1.2 `ext_info` 数组（核心）

是 `[{ext_key, ext_value}, ...]` 形式，**全部 5 个 key 都是必填**：

| `ext_key` | `ext_value` 内容 | 说明 |
|---|---|---|
| `merchant_order_status` | 状态英文码 | 见 §2 状态枚举 |
| `merchant_biz_type` | `3C_RENT` | 业务类目（固定）|
| `merchant_order_link_page` | `/pages/order-detail/order-detail?id=Oxxx` | 商家小程序订单详情页路径（**一笔订单全程一致**） |
| `tiny_app_id` | `2021000000000000` | 商家小程序 APPID（即 `AlipayConfig.app_id()`） |
| `business_info` | JSON 字符串 | 见 §3 业务信息字段 |

### 1.3 `item_order_list` 商品信息

每个商品是一个对象：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `item_name` | String | ✅ | 商品名（建议 `{商家名}+{商品名}`）|
| `quantity` | Number | 选 | 数量（与 unit_price 成对） |
| `unit_price` | Price | 选 | 单价（与 quantity 成对） |
| `ext_info` | List | ✅ | 必须包含 `image_material_id` |

商品级 `ext_info` 唯一必填字段：

| `ext_key` | `ext_value` |
|---|---|
| `image_material_id` | 通过「上传商品文件」接口获得的 material_id |

> ⚠️ **`image_material_id` 是新依赖**：得先调上传接口把商品图传一遍，拿到 material_id 才能在 sync 时引用。否则 item_order_list 校验通不过。

---

## 二、状态枚举（3C_RENT 全集，含中英文 + 服务消息 + push）

完整 22 个状态：

| # | 中文 | 英文 (`merchant_order_status`) | 核心 | 服务消息 | Push |
|---|---|---|---|---|---|
| 1 | 申请中 | `APPLYING` | 否 | 否 | 否 |
| 2 | 审批中 | `APPROVAL` | 否 | ✅ | 否 |
| 3 | 审核拒绝 | `REJECT` | 否 | ✅ | ✅ |
| 4 | 待支付 | `WAIT_PAY` | 否 | ✅ | 否 |
| 5 | 已关闭 | `CLOSED` | 否 | 否 | 否 |
| 6 | 待发货 | `TO_SEND_GOODS` | 否 | 否 | 否 |
| 7 | 已发货 | `IN_DELIVERY` | 否 | ✅ | ✅ |
| 8 | **租赁中** | `IN_THE_LEASE` | **✅** | ✅ | ✅ |
| 9 | **履约完成** | `EXERCISED` | **✅** | ✅ | ✅ |
| 10 | 已逾期 | `OVERDUE` | 否 | ✅ | ✅ |
| 11 | 租赁到期 | `RENT_DUE` | 否 | ✅ | ✅ |
| 12 | 归还逾期 | `RETURN_OVERDUE` | 否 | ✅ | ✅ |
| 13 | 买断中 | `IN_THE_BUYOUT` | 否 | ✅ | ✅ |
| 14 | 归还中 | `IN_THE_BACK` | 否 | 否 | 否 |
| 15 | 待赔付 | `TO_BE_PAID` | 否 | ✅ | ✅ |
| 16 | 续租中 | `RELET` | 否 | ✅ | 否 |
| 17 | 已买断 | `BUYOUT` | 否 | ✅ | 否 |
| 18 | 已归还 | `FINISHED` | 否 | ✅ | ✅ |
| 19 | 待商家确认 | `PENDING` | 否 | 否 | 否 |
| 20 | 租赁结束 | `END_OF_LEASE` | 否 | 否 | 否 |
| 21 | 待免押 | `DEPOSIT_WAIVER` | 否 | 否 | 否 |
| 22 | 试用中 | `ON_TRIAL` | 否 | 否 | 否 |

「**核心**」标记的两个状态（`IN_THE_LEASE` / `EXERCISED`）才是有效订单核心状态。
「**服务消息**」是 ✅ 的状态切换时，用户能在支付宝「服务提醒」入口看到这条订单消息提醒。

### 2.1 状态机流转规则（节选关键链路）

> 文档明确说支持**跨状态跳转**，首次同步**不强制是 APPLYING**。下面表格只截了本项目涉及到的核心链路：

| 当前 | 允许的后置 |
|---|---|
| `DEPOSIT_WAIVER` 待免押 | `CLOSED` / `APPROVAL` / `TO_SEND_GOODS` / `PENDING` / `DEPOSIT_WAIVER` / `REJECT` |
| `TO_SEND_GOODS` 待发货 | `IN_DELIVERY` / `CLOSED` / `IN_THE_LEASE` / `OVERDUE` / `IN_THE_BACK` / `EXERCISED` / `RENT_DUE` / `RELET` / `IN_THE_BUYOUT` / `TO_BE_PAID` / `RETURN_OVERDUE` / `FINISHED` / `BUYOUT` |
| `IN_DELIVERY` 已发货 | `IN_THE_LEASE` / `ON_TRIAL` / `CLOSED` / `BUYOUT` / `EXERCISED` / ... |
| `IN_THE_LEASE` 租赁中 | `RENT_DUE` / `OVERDUE` / `IN_THE_BACK` / `RELET` / `IN_THE_BUYOUT` / `EXERCISED` / `END_OF_LEASE` / `FINISHED` / `BUYOUT` / `CLOSED` / ... |
| `RENT_DUE` 租赁到期 | `IN_THE_BACK` / `RELET` / `RETURN_OVERDUE` / `FINISHED` / `TO_BE_PAID` / `IN_THE_BUYOUT` / `BUYOUT` |
| `OVERDUE` 已逾期 | `IN_THE_BACK` / `FINISHED` / `RELET` / `BUYOUT` / ... |
| `IN_THE_BACK` 归还中 | `FINISHED` / `BUYOUT` / `TO_BE_PAID` |
| `FINISHED` 已归还 | `FINISHED` （终态，只能停留） |
| `CLOSED` 已关闭 | `CLOSED` （终态） |
| `PENDING` 待商家确认 | `APPROVAL` / `TO_SEND_GOODS` / `WAIT_PAY` / `REJECT` / `CLOSED` / `APPLYING` / `PENDING` |

---

## 三、`business_info` 业务字段（按状态有不同必填）

`business_info` 是 JSON 字符串，所有字段类型都是 String：

| 字段 | 含义 | 本项目数据来源 |
|---|---|---|
| `total_rent` | 总租金 | `order.amount` |
| `lease` | 租期（如 "15 天" / "12 期"） | `order.days` 拼装 |
| `cash_pledge` | 商品押金 | `order.deposit_freeze` |
| `thaw_deposit` | 已冻结押金 | `order.deposit_freeze`（与 cash_pledge 同源） |
| `first_rent` | 首期租金 | 我们没分期，可不传 |
| `receiving_time` | 收货时间 `yyyy-MM-dd HH:mm:ss` | 用户在小程序点签收 / 物流签收 |
| `delivery_time` | 发货时间 `yyyy-MM-dd HH:mm:ss` | `order.shipped_at` |
| `rent_due_date` | 租赁到期日 `yyyy-MM-dd` | `order.end_date` |
| `lease_period` | 租赁周期（`2026.05.18--2026.06.04`）| `start_date + "--" + end_date` |
| `give_back_date` | 应还机日 | `order.end_date` |
| `courier_number` | 快递单号 | `order.logistics_no` |
| `overdue_amount` | 逾期金额 | 未实现 |
| `buy_amount` | 买断金额 | 未实现 |
| `payment_amount` | 赔付金额 | 未实现 |
| `real_date` | 实际续租/买断/还机日 | 未实现 |
| `fast_examine_url` | 极速审核 URL（`DEPOSIT_WAIVER` / `ON_TRIAL` 特有） | 未实现 |

### 3.1 各状态下的"是否必填"差异

文档对**同一字段**在不同状态下的必填要求不同。**核心规则**：

- `total_rent`、`lease`：**几乎所有状态都必填**
- `DEPOSIT_WAIVER` / `APPLYING` / `APPROVAL` / `REJECT` / `WAIT_PAY` / `CLOSED` / `PENDING` / `END_OF_LEASE` / `ON_TRIAL`：业务字段大部分非必填
- `TO_SEND_GOODS`：`thaw_deposit` 必填
- `IN_DELIVERY`：`thaw_deposit` + `delivery_time` + `courier_number` 必填
- `IN_THE_LEASE` / `RENT_DUE` / `OVERDUE` / `EXERCISED` / `RETURN_OVERDUE` / `RELET` / `IN_THE_BUYOUT` / `BUYOUT` / `FINISHED` / `IN_THE_BACK` / `TO_BE_PAID`：`thaw_deposit` + `delivery_time` + `rent_due_date` + `courier_number` + `lease_period` + `give_back_date` 这些都必填
- `OVERDUE`：额外 `overdue_amount` 必填
- `IN_THE_BUYOUT` / `BUYOUT`：额外 `buy_amount` 必填
- `TO_BE_PAID`：额外 `payment_amount` 必填
- `RELET`：额外 `real_date` 必填

> **简化原则**：本项目**永远填齐所有有值的字段**，没用到的（如 buy_amount/payment_amount）置空字符串 `""` 或不传。

---

## 四、本项目内部状态 → 3C_RENT 状态映射

### 4.1 当前内部状态机

```
audit (待免押)
  ├──[用户主动取消]──> cancelled
  ├──[免押成功]──> send (待发货)
                    ├──[用户申请取消]──> pending_cancel
                    │                    ├──[商家驳回]──> send
                    │                    └──[商家同意]──> cancelled
                    └──[商家发货]──> recv (待收货)
                                      └──[用户签收]──> using (租赁中)
                                                        ├──[到期]──> return / overdue
                                                        └──[超时未还]──> overdue
                                                                          └──> done (终态)
```

### 4.2 精确映射表（最终版，**覆盖之前的推断**）

| 内部 status | 中文 | 同步给阿里的 `merchant_order_status` | 理由 |
|---|---|---|---|
| `audit` | 待免押 | `DEPOSIT_WAIVER` | **完全语义匹配** —— 阿里专门为信用免押产品留的状态 |
| `send` | 待发货 | `TO_SEND_GOODS` | 完全匹配 |
| `pending_cancel` | 取消审核中 | `PENDING` | 文档原文「待商家确认」，最贴近本场景 |
| `recv` | 待收货 | `IN_DELIVERY` | 用户视角订单已发货等签收 |
| `using` | 租赁中 | `IN_THE_LEASE` | 完全匹配 |
| `return` | 待归还 | `RENT_DUE` | 租赁到期，等用户归还（→ `IN_THE_BACK` 用户回寄后） |
| `overdue` | 已逾期 | `OVERDUE` | 完全匹配 |
| `done` | 已归还 | `FINISHED` | 完全匹配（终态） |
| `cancelled` | 已取消 | `CLOSED` | 阿里没"已取消"，统一关闭 |

### 4.3 本项目暂不接入的状态（业务未做）

| 阿里状态 | 启用时机 |
|---|---|
| `APPLYING` / `APPROVAL` / `REJECT` | 接入风控人工审核流程后 |
| `WAIT_PAY` | 如果改成"先下单再付款"流程（当前免押模式不需要） |
| `IN_THE_BACK` 归还中 | 接入"用户寄回 + 物流追踪"后 |
| `IN_THE_BUYOUT` / `BUYOUT` | 接入"租满买断"功能后 |
| `RELET` | 接入"续租"功能后 |
| `TO_BE_PAID` | 接入"质检 + 损坏赔付"流程后 |
| `RETURN_OVERDUE` | 接入"回寄物流逾期判定"后 |
| `END_OF_LEASE` | 接入"租赁结束清算"后 |
| `ON_TRIAL` | 接入"试用"功能后 |

---

## 五、`alipay_client.py:merchant_order_sync` 必须重写

### 5.1 当前实现的错误

```python
# 当前（错的）
model.status = status                  # ❌ 没这个顶层字段
model.biz_type = biz_type              # ❌ 没这个顶层字段
model.ext_info = json.dumps({...})     # ❌ 不是 JSON 字符串，是 OrderExtInfo 数组
model.logistics_info_list = [...]      # ❌ 3C_RENT 类目根本不支持
```

### 5.2 正确实现的伪代码

```python
from alipay.aop.api.domain.AlipayMerchantOrderSyncModel import AlipayMerchantOrderSyncModel
from alipay.aop.api.domain.OrderExtInfo import OrderExtInfo
from alipay.aop.api.domain.ItemOrderInfo import ItemOrderInfo

model = AlipayMerchantOrderSyncModel()
model.out_biz_no = order.id
model.buyer_id = order.user_id           # 或 model.buyer_open_id = ...
model.order_type = "SERVICE_ORDER"
model.order_create_time = fmt("yyyy-MM-dd HH:mm:ss", order.created_at)
model.order_modified_time = fmt_ms()                       # 毫秒精度
model.amount = "89.70"
model.pay_amount = "89.70"
model.category_id = "C100845427"

# ── 商品信息列表（含商品图 material_id）──
item_ext = OrderExtInfo()
item_ext.ext_key = "image_material_id"
item_ext.ext_value = order.alipay_image_material_id  # 上传商品文件接口获得
item = ItemOrderInfo()
item.item_name = "观澜数码租赁 - PICO 4 Pro"
item.quantity = "1"
item.unit_price = "89.70"
item.ext_info = [item_ext]
model.item_order_list = [item]

# ── 订单扩展字段：状态 / 类型 / 详情链接 / appid / business_info ──
business_info = json.dumps({
    "total_rent":      str(order.amount),
    "lease":           f"{order.days}天",
    "cash_pledge":     str(order.deposit_freeze),
    "thaw_deposit":    str(order.deposit_freeze),
    "delivery_time":   fmt("yyyy-MM-dd HH:mm:ss", order.shipped_at) if order.shipped_at else "",
    "courier_number":  order.logistics_no or "",
    "rent_due_date":   order.end_date,
    "lease_period":    f"{order.start_date}--{order.end_date}",
    "give_back_date":  order.end_date,
}, ensure_ascii=False)

def _ext(k, v):
    e = OrderExtInfo(); e.ext_key = k; e.ext_value = v; return e

model.ext_info = [
    _ext("merchant_order_status",   alipay_status),                  # 见 §4.2 映射
    _ext("merchant_biz_type",       "3C_RENT"),
    _ext("merchant_order_link_page","/pages/order-detail/order-detail?id=" + order.id),
    _ext("tiny_app_id",             AlipayConfig.app_id()),
    _ext("business_info",           business_info),
]

req = AlipayMerchantOrderSyncRequest(biz_model=model)
req.notify_url = AlipayConfig.NOTIFY_URL_MERCHANT_ORDER_SYNC
resp_str = self._client.execute(req)
```

### 5.3 关键改动清单

| 项 | 当前 | 改成 |
|---|---|---|
| `status` / `biz_type` 字段 | 顶层 | 都进 `ext_info` 数组 |
| `ext_info` 类型 | `json.dumps({...})` | `[OrderExtInfo(ext_key, ext_value), ...]` |
| `item_order_list` | 一直没用 | 必填，每个 item 还要带 `image_material_id` |
| `logistics_info_list` | 强行塞了 | 删除，物流单号放 `business_info.courier_number` |
| `order_create_time` | 没传 | 必填 |
| `order_modified_time` | 没传 | 必填（毫秒精度） |
| `tiny_app_id` | 没传 | 必填，从 `AlipayConfig.app_id()` 取 |
| `merchant_order_link_page` | 没传 | 必填，前端订单详情页路径 |
| `category_id` | 没传 | 建议传 `C100845427` |
| 状态枚举 | 推断的英文码 | 见 §4.2 真实映射 |

---

## 六、`image_material_id` 来源（新依赖）

`item_order_list[].ext_info[image_material_id]` 是必填，**没它整个请求会被打回**。

获取方式：
1. **接口**：`alipay.open.app.material.image.upload` 或「上传商品文件」（具体名以你签约的产品文档为准）
2. **入参**：商品图片（多媒体文件 / URL）
3. **返回**：`material_id`（如 `2019082600502200000000566463`），需**落库到 product 表**
4. **复用**：同一商品所有订单都用同一 material_id（不要每次重传）

### 6.1 落地步骤

1. **数据库**：`product` 表加字段 `alipay_image_material_id`
2. **后台**：商品管理页加按钮「上传到支付宝」，触发上传接口，结果写入 `alipay_image_material_id`
3. **同步**：在 `_build_extend_info` 取 `product.alipay_image_material_id` 拼到 item_ext
4. **没上传的商品**：sync 时报错落 `notify_log`，提示运营去后台先上传

> **过渡方案**：如果暂时不想做上传流程，可以在 `tiny_app_id` 后台手工上传几张商品图拿到 material_id，先硬编码到 `product` 数据里。但这只对少量 SKU 可行。

---

## 七、触发时机（业务事件 → sync 调用）

| 业务事件 | 内部状态 | → 同步 `merchant_order_status` | 触发位置 |
|---|---|---|---|
| 用户下单（未免押）| 创建 audit | `DEPOSIT_WAIVER` | `routes/orders.py:create_order` 末尾 |
| 免押授权完成 | audit → send | `TO_SEND_GOODS` | `notify_auth_freeze` 推进 send 后 |
| 用户申请取消 | send → pending_cancel | `PENDING` | `routes/orders.py:cancel` 进 pending 分支后 |
| 商家驳回取消 | pending_cancel → send | `TO_SEND_GOODS` | `admin.py:cancel-reject` |
| 商家同意取消 | pending_cancel → cancelled | `CLOSED` | `admin.py:cancel-approve` |
| 商家发货 | send → recv | `IN_DELIVERY`（必带 `courier_number` + `delivery_time`） | `admin.py:ship_order` |
| 用户签收（支付宝端点击 OR 物流确认） | recv → using | `IN_THE_LEASE` | `notify_merchant_order_sync` 或后台 |
| 到期日（定时任务）| using → return | `RENT_DUE` | 待实现的 cron |
| 逾期（定时任务）| return → overdue | `OVERDUE` | 待实现的 cron |
| 验收完成 | overdue/return → done | `FINISHED` | 商家后台「验收」按钮 |

---

## 八、回调 notify_url

阿里在用户端做了某些动作后会推送到 `NOTIFY_URL_MERCHANT_ORDER_SYNC`：

- 用户点「确认收货」/「续租」/「申请买断」/「申请赔付」等操作时
- 推送的 ext_info 里会带 `merchant_order_status` 表示用户希望转入的状态

当前 `routes/alipay.py:notify_merchant_order_sync` 只落日志没做业务推进。当接入 `RELET` / `IN_THE_BUYOUT` / `TO_BE_PAID` 等用户主动状态时，必须解析 `ext_info` 反向映射到内部状态机。

---

## 九、本项目改造工作量

### 9.1 P0 必做（让订单中心能展示）

| 项 | 工作量 |
|---|---|
| `alipay_client.py:merchant_order_sync` 完全重写（按 §5.2 伪代码）| 1 小时 |
| `order_sync.py:_STATUS_MAP` 完全重做（按 §4.2 映射）| 5 分钟 |
| `order_sync.py:_build_extend_info` 改成只输出 business_info 用的字段 | 10 分钟 |
| `order_sync.py:_build_logistics_info` **整个删除** | 1 分钟 |
| order_repo 加 `alipay_image_material_id` 字段（落到 product 表） | 5 分钟 |
| **占位过渡**：material_id 暂时用空串，先看能否走通；如果阿里强校验再补上传流程 | - |
| 在所有 §7 列的触发点接 `sync_order(oid)` 调用（共 6 处） | 30 分钟 |

### 9.2 P1（信号完善）

- `notify_merchant_order_sync` 反向解析 `ext_info[merchant_order_status]` 推进内部状态机
- 定时任务推进 `RENT_DUE` / `OVERDUE`
- 上传商品图拿 `material_id` 的后台流程
- 在「订单管理」页展示每条订单的 sync 状态 + 手动重试按钮（**已实现**）

### 9.3 P2（功能扩展）

- 接入 `IN_THE_BUYOUT` / `BUYOUT`（买断功能）
- 接入 `RELET`（续租功能）
- 接入 `TO_BE_PAID`（赔付流程）
- 接入 `RETURN_OVERDUE`（回寄物流逾期）

---

## 十、常见错误码

| sub_code | 原因 | 处理 |
|---|---|---|
| `ILLEGAL_ARGUMENT` | 字段格式 / 状态枚举非法 | 看 `sub_msg`：缺字段就补字段，枚举错就改 |
| `OPERATION_NOT_SUPPORT` | 类目未签约 / `merchant_biz_type` 不被认可 | 去开放平台「订单中心」类目签约页 |
| `IMAGE_NOT_EXIST` / 类似 | `image_material_id` 错误或未上传 | 重传图片拿新 material_id |
| `INVALID_STATUS_TRANSITION` | 状态机违反流转规则（参考 §2.1） | 看当前阿里端订单的状态，按允许链路逐步推 |
| `TRADE_HAS_SUCCESS` | 同 `out_biz_no` 已存在且字段冲突 | 检查 amount/buyer_id 等是否对得上 |

---

## 十一、相关代码 / 文件索引

| 文件 | 作用 | 改动状态 |
|---|---|---|
| `houdan/app/alipay_client.py:merchant_order_sync` | SDK 封装 | ❌ **需重写** |
| `houdan/app/order_sync.py:_STATUS_MAP` | 状态映射 | ❌ **需重做** |
| `houdan/app/order_sync.py:_build_extend_info` | business_info 字段组装 | ❌ **需简化** |
| `houdan/app/order_sync.py:_build_logistics_info` | 物流信息组装 | ❌ **可删除** |
| `houdan/app/order_sync.py:sync_order` | 主入口 | ✅ 主流程 OK |
| `houdan/app/routes/alipay.py:notify_merchant_order_sync` | 回调 | ⚠️ 反向映射待补 |
| `houdan/app/routes/admin.py:/orders/<oid>/sync` | 后台手动重试 | ✅ |
| `houdan/manager/pages/Orders.vue` | 后台展示 sync 状态 | ✅ |

---

## 十二、参考资料

- **官方接入方案**：[https://opendocs.alipay.com/solution/0de1h8](https://opendocs.alipay.com/solution/0de1h8)
- **接口文档**：`alipay.merchant.order.sync` —— OpenDocs 搜索接口名
- **类目说明**：「线上租赁 3C_RENT」类目下的字段约定均以官方文档为准
- **本类目类目 ID**：`C100845427`
