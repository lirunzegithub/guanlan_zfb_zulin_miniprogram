"""全局 Repository 单例 + 种子数据装载 + 老 JSON 数据迁移。

存储已切到 SQLite（单文件 data/app.db）。
切回 Json 只需把 SqliteRepository 换回 JsonRepository，业务代码零修改。
"""
import json
import os

from .sqlite_store import SqliteRepository
from .seed import (
    BANNERS_SEED, CATEGORIES_SEED, PRODUCTS_SEED, ADDRESSES_SEED,
    USERS_SEED, ORDERS_SEED, STAFFS_SEED, FAQS_SEED,
)

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
DB_PATH  = os.path.join(DATA_DIR, "app.db")


# ============ 业务实体 ============
banner_repo = SqliteRepository(
    DB_PATH, "banners",
    default_fields={
        "position": "secondary", "slot": 0, "title": "", "subtitle": "",
        "tag": "", "tag_style": "", "image_url": "", "bg": "",
        "link_type": "none", "link_value": "",
        "start_at": None, "end_at": None,
    },
)

category_repo = SqliteRepository(
    DB_PATH, "categories",
    default_fields={
        "name": "", "parent_id": 0, "icon_url": "", "cover_url": "",
        "description": "", "service_id": "", "alipay_category": "",
    },
)

address_repo = SqliteRepository(
    DB_PATH, "addresses",
    default_fields={
        "user_id": "", "receiver_name": "", "receiver_phone": "",
        "province": "", "city": "", "district": "", "detail": "",
        "zip_code": "", "is_default": False,
        "source": "manual",
    },
)

product_repo = SqliteRepository(
    DB_PATH, "products",
    default_fields={
        "cat_id": 0, "name": "",
        # covers 是封面图数组（URL/相对路径），多图渲染轮播。
        # cover_url 始终镜像 covers[0]（兼容旧数据/旧列表卡的 swatch）。
        "covers": [],
        "cover_url": "",
        "min_price": 20.0, "rent_unit": "天",
        # 押金额度：必填字段（admin 写入时校验 >0），订单创建时拷贝到 order.deposit_freeze
        # 默认 2000，避免历史/迁移数据漏配押金导致 0 押金风险
        "deposit_amount": 2000.0, "min_rent_days": 1, "max_rent_days": 0,
        "stock": 0, "sales": 0, "rented_count": 0,
        "service_id": "",
        "intro": "", "shipping": "顺丰速运、上门自提",
        "shipping_note": "",
        # 默认 20 元/天起步，避免后台漏配价格导致 0 元租赁
        "price_tiers": [{"from": 1, "price": 20.0}],
        "price_curve": [], "rights": [],
        "real_shots": [], "spec_groups": [],
        # 定损标准：每商品独立配置；详情页据此渲染定损表
        # 结构 { enabled, title, headers:{type,degree,deprec,insurance}, groups:[{type, rows:[{degree, depreciation, insurance, depreciation_highlight, insurance_highlight}]}], notice }
        "damage_standard": {},
        "shop": {},
        # SKU 选择行在小程序详情页的标题文案，运营可改成"容量"/"版本"/"成色"等。
        # 只影响展示；商品有几个 SKU 一律看 sku_repo。
        "sku_option_name": "SKU",
        "status": "on",
        # 支付宝订单中心商品图素材 ID（通过「上传商品文件」接口获得）
        # alipay.merchant.order.sync 的 item_order_list 必填字段
        # 由 admin 保存商品时自动触发：covers[0] 变 → 上传 → 写回这里
        "alipay_image_material_id": "",
        # 上次上传过的 cover URL；跟 covers[0] 比，相同则跳过重传，省 API 配额
        "alipay_image_source": "",
    },
)

# SKU（独立表；按 product_id 反查）
#
# 【单一数据源】价格 / 押金 / 库存 / 销量只存在于 SKU 层，商品层不再是真相来源。
# 每个商品恒定至少有一个 SKU：新建商品时后端自动建「标准版」，存量商品由
# _backfill_default_skus() 在启动时补建。商品 payload 里同名的老字段只作为
# 「新建时第一个 SKU 的初始值」和极端兜底，任何下单路径都不再读它们。
#
# 为什么不塞进 product.payload 的数组字段：库存扣减用的是 sqlite_store.try_decrement，
# SQL 里写死 json_set(payload, '$.stock', ...) 的单条件更新来防超卖。若 SKU 存成数组，
# 路径要变成 '$.skus[i].stock'，而数组下标在增删 SKU 后会移位，并发下可能扣错行。
# 独立成表后每个 SKU 一行，try_decrement(sku_id, "stock") 原样复用，防超卖保证不打折。
#
# 建表由 SqliteRepository.__init__ 的 CREATE TABLE IF NOT EXISTS 完成，
# 应用启动 import 本模块时自动执行，无需任何迁移脚本。
sku_repo = SqliteRepository(
    DB_PATH, "skus",
    default_fields={
        "product_id": 0,
        # SKU 名，如 "128G 深空灰"；同一商品下不允许重名（admin 层校验）
        "name": "",
        # SKU 封面：可选。留空则前端回落到商品的 covers[0]
        "cover_url": "",
        # 价格 / 押金 / 库存：下单一律以这里为准
        "price_tiers": [{"from": 1, "price": 20.0}],
        "min_price": 20.0,        # 由 price_tiers 派生，保存时重算
        "price_curve": [],        # 同上
        "deposit_amount": 2000.0,
        "stock": 0,
        "sales": 0,
        "status": "on",           # on 可选 / off 隐藏（不在小程序露出，也不可下单）
        # 展示顺序：越小越靠前。写进 payload 后由 SqliteRepository 同步到 sort_key 列，
        # repo.list() 恒按 `sort_key ASC, id ASC` 返回，所以小程序里 SKU 的先后
        # 完全由后台拖拽决定（见 admin.py 的 skus_reorder）。
        "sort": 0,
        # SKU 有独立封面时，素材单独上传一份；留空则同步订单时回落到商品的 material_id
        "alipay_image_material_id": "",
        "alipay_image_source": "",
    },
)

# 自动补建的第一个 SKU 的名字。单 SKU 商品在小程序不显示选择行，这个名字只在后台可见。
DEFAULT_SKU_NAME = "标准版"


def ensure_default_sku(p: dict) -> dict | None:
    """商品还一个 SKU 都没有时，用商品级的价格/押金/库存建一条「标准版」。

    已经有 SKU 的商品原样返回 None，因此重复调用安全（启动回填 + 新建商品共用）。
    """
    if not p or not p.get("id"):
        return None
    if sku_repo.find(product_id=p["id"]):
        return None

    from app.pricing import normalize_tiers, min_unit_price, derive_price_curve
    tiers = normalize_tiers(p.get("price_tiers") or [{"from": 1, "price": 20.0}])
    return sku_repo.create({
        "product_id":     p["id"],
        "name":           DEFAULT_SKU_NAME,
        "cover_url":      "",
        "price_tiers":    tiers,
        "min_price":      min_unit_price(tiers),
        "price_curve":    derive_price_curve(tiers),
        "deposit_amount": float(p.get("deposit_amount") or 0),
        "stock":          int(p.get("stock") or 0),
        "sales":          int(p.get("sales") or 0),
        "status":         "on",
    })

# 评论（独立表；按 product_id 反查）
comment_repo = SqliteRepository(
    DB_PATH, "comments",
    default_fields={
        "product_id": 0,
        "user_id": "",
        "user": "",
        "avatar_color": "",
        "stars": 5,
        "content": "",
        # 评价配图：相对路径数组（/product/asset/products/uploads/comments/<f>）
        # 列表/详情接口返回时会拼成绝对 URL，方便小程序 <image> 直接消费
        "images": [],
    },
)

# 用户（字符串 id = 支付宝 user_id，16 位数字串）
user_repo = SqliteRepository(
    DB_PATH, "users",
    default_fields={
        "nickname": "", "avatar": "",
        "real_name": "", "phone": "", "id_card": "",
        "verified": False,
        # 支付宝实名认证 certify_id 复用：通过后 3 个月内对同一用户复用不重复 KYC。
        # last_certify_at = 上次 initialize 时间戳；用于 certify_init 决策是否走旧 id。
        "last_certify_id": "",
        "last_certify_at": 0,
    },
    id_type="str",
)

# 订单（字符串 id，如 "O04E792A90891"，由业务侧生成）
order_repo = SqliteRepository(
    DB_PATH, "orders",
    default_fields={
        "user_id": "",
        "product_id": 0, "product_name": "",
        # SKU 快照：历史订单与无 SKU 的极端情况恒为 0 / ""，各端据此决定是否显示 SKU 行
        "sku_id": 0, "sku_name": "",
        "price_per_day": 0.0, "days": 0,
        # amount = 实付总租金（已扣优惠）；original_amount = 未扣前的总租金
        "amount": 0.0, "original_amount": 0.0,
        # 优惠券核销快照：未用券时全部为空/0
        "coupon_id": 0, "user_coupon_id": 0,
        "coupon_name": "", "coupon_threshold": 0.0,
        "coupon_discount": 0.0, "discount_amount": 0.0,
        "price_tiers": [],
        "start_date": "", "end_date": "", "ship_days": 0,
        # 真实签收留痕（顺丰轨迹驱动跳变时落）。老订单与非顺丰单恒为 0 / ""。
        #   delivered_at      真实签收时间 unix 秒
        #   delivered_source  签收信息来源："sf" = 顺丰轨迹；"" = 没拿到，走的定时器保底
        #   ship_days_planned 下单时约定的物流免租期原值。提前签收会把 ship_days
        #                     改写成真实物流天数并据此重算 end_date，原值存这里备查，
        #                     不然改完就再也说不清"当初答应用户几天免租"了。
        "delivered_at": 0, "delivered_source": "", "ship_days_planned": 0,
        # 物流轨迹缓存（订单详情页展示用，见 app/order_logistics.py）。
        # 订单详情是最常被刷的页面，不缓存就等于每次进页面都打一次顺丰。
        "logistics_routes": [], "logistics_synced_at": 0,
        # 用户下单时填的备注（确认订单页「备注」行）。与 order_note_repo 完全不同：
        # 那个是后台工作人员的审计日志，用户看不见；这个是用户写给商家的，双方可见。
        # payload 是 JSON blob，老订单没这个 key，读取处一律 .get() 兜底，无需迁移。
        "user_remark": "",
        "deposit_freeze": 0.0, "credit": False,
        # 该订单"实际向支付宝冻结的总金额"快照（押金 or 押金+租金，下单时按 settings.freeze_includes_rent 算）
        # 下单后写一次就不动；后台改 setting 不影响历史订单
        "freeze_amount":        0.0,
        "freeze_includes_rent": True,
        # 首期租金普通交易（新订单 pay → audit）
        "rent_out_trade_no": "", "rent_trade_no": "", "rent_trade_status": "",
        "rent_paid_at": 0, "rent_payment_error": "", "rent_payment_raw": {},
        "rent_refund_request_no": "", "rent_refunded_at": 0, "rent_refunded_amount": 0.0,
        "rent_refund_error": "", "rent_refund_raw": {},
        "rent_capture_attempts": 0,
        # 综合授权后自动收租金的留痕：last_at 供定时重试算退避，
        # last_error 是 auth_trade_pay 抛出的支付宝原文（含 sub_code/sub_msg）
        "rent_capture_last_at": 0, "rent_capture_last_error": "",
        "status": "audit",
        "address_id": 0, "address_snapshot": {},
        "lock_until": None, "certify_id": None,
        # send_at = audit→send（芝麻免押成功）落地的 unix 秒，前端 48h 发货倒计时基准
        "send_at": None,
        # 物流：发货时由 admin 写入；shipped_at 为发货 unix 秒
        "logistics_company": "",   # 快递公司编码（SF/JD），与 app.logistics.COURIERS 对齐
        "logistics_no": "",        # 运单号（已大写 + 去空白）
        "shipped_at": None,
        # 光影库存系统货号绑定：发货时填写（按 settings.ship_huohao_required 决定选填/必填）
        # 商品卡片/租赁记录不再存快照，展示时按 item_huohao 实时从光影拉取（见 _order_view）
        "item_huohao": "",
        # 归还物流：用户在 using / return / overdue 状态填写后写入
        # returned_at  = 用户提交寄回信息的 unix 秒（同时即 return_inspecting_at）
        # return_approved_at = 商家点"核验通过"并下发解冻的 unix 秒
        "return_logistics_company": "",
        # 用户点选 segment 时的快递公司中文名（如"顺丰速运"），原样落库供展示，
        # 不再依赖后端 code→name 查表，做到"选什么显示什么"
        "return_logistics_company_name": "",
        "return_logistics_no":      "",
        "returned_at":              None,
        "return_approved_at":       None,
        # 支付宝商家订单履约同步状态（alipay.merchant.order.sync）
        # sync_status = 最近一次成功同步的支付宝状态枚举（WAIT_USE / IN_USE / ...）
        # sync_ok     = 最近一次同步是否成功；用于前端展示 + 失败重试入口
        # sync_at     = 最近一次同步时间（unix 秒）
        # sync_err    = 最近一次同步失败原因（成功后清空）
        "sync_status": "", "sync_ok": False, "sync_at": None, "sync_err": "",
        # alipay 资金授权号（freeze notify 写入，trade.pay 时复用）
        "alipay_auth_no": "", "alipay_out_request_no": "", "alipay_operation_id": "",
        # 预授权重试支持：同一订单可能多次发起 freeze（免押取消→回退押金）。
        # 支付宝授权订单按 out_order_no 唯一，复用同一号会被拒"订单已存在"，
        # 故每次冻结生成带递增后缀的 out_order_no（首次裸号，之后 _A2/_A3…）。
        #   alipay_freeze_attempts = 已发起冻结次数，决定下一次后缀
        #   alipay_out_order_no    = 当前生效的支付宝授权订单号（裸号或带后缀）
        # 旧订单行无这两个字段，读取处一律 .get(k) or 兜底，无需数据迁移。
        "alipay_freeze_attempts": 0, "alipay_out_order_no": "",
        # 取消撞上冻结成功的自动解冻标记：
        #   auto_unfreeze_reason   = 触发来源（freeze_after_cancel / query_frozen_after_cancel /
        #                            user_cancel_frozen），空 = 非自动解冻
        #   orphan_freeze_alerts   = 非"当前生效号"的授权也冻结成功的告警记录（异常场景，
        #                            不自动动资金，人工核实后解冻）
        "auto_unfreeze_reason": "", "orphan_freeze_alerts": [],
    },
    id_type="str",
)

# 预授权扣款流水（alipay.trade.pay 发起的每笔扣款一条记录）
# id 就是 out_trade_no，由后端按 oid + 时间戳生成；阿里端用 out_trade_no 幂等
trade_repo = SqliteRepository(
    DB_PATH, "alipay_trades",
    default_fields={
        "order_id":     "",        # 关联本地订单 id
        "amount":       0.0,       # 本次扣款金额
        "subject":      "",        # 扣款标题（最终传给支付宝的字符串：【分类】具体说明）
        "reason_type":  "",        # 扣款原因分类：RENT_SERVICE / OVERDUE_PENALTY / DAMAGE_LOSS / USER_CONFIRMED_OTHER
        "reason_detail":"",        # 操作员填写的具体说明（自由文本）
        "auth_no":      "",        # 调用时用的支付宝授权号（来自 order.alipay_auth_no）
        "auth_confirm_mode": "NOT_COMPLETE",   # COMPLETE 转完自动解冻剩余；NOT_COMPLETE 继续冻结
        "product_code": "PREAUTH_PAY",
        "status":       "INIT",    # INIT / WAIT_BUYER_PAY / TRADE_SUCCESS / TRADE_CLOSED / TRADE_FINISHED / FAILED
        "trade_no":     "",        # 阿里返回的支付宝交易号
        "buyer_logon_id": "",      # 阿里返回的买家账号（脱敏）
        "gmt_payment":  "",        # 阿里返回的支付时间
        "receipt_amount": 0.0,     # 实收金额
        "fail_code":    "",        # 失败时填 sub_code
        "fail_msg":     "",        # 失败时填 sub_msg
        "closed_by":    "",        # 关闭来源：admin / notify / system
        "raw_pay":      {},        # 发起扣款时阿里同步响应原文
        "raw_query":    {},        # 最近一次查询的原文
        "raw_close":    {},        # close 接口响应原文
        # 退款流水：每笔退款一条记录
        # {out_request_no, amount, reason, status, fund_change, operator, created_at,
        #  refund_at, raw_refund, raw_query, fail_code, fail_msg}
        # status 枚举：INIT / SUBMITTED / REFUND_SUCCESS / FAILED
        "refunds":          [],
        # 累计已退款金额，多次退款时由后端 sum 后写入；用于校验"本次退款是否超出剩余可退"
        "refunded_amount":  0.0,
        # 用户对本笔扣款发起的退款申请（同一笔同时最多一个活跃申请；驳回后允许覆盖式重提）
        # {status, reason, applied_at, reviewed_at, reviewer, rejected_reason,
        #  refund_out_request_no}
        # status 枚举：PENDING / APPROVED / REJECTED（空 dict 表示用户未发起申请）
        "refund_apply":     {},
        "operator":     "",        # 触发操作的工作人员 username
        "paid_at":      None,
        "closed_at":    None,
    },
    id_type="str",
)

# 续租服务单（字符串 id，如 R8F2A1C...）。续租款走用户主动的普通支付，
# 不直接从原租赁订单的免押授权额度中扣除。
renewal_repo = SqliteRepository(
    DB_PATH, "renewals",
    default_fields={
        "order_id": "", "user_id": "",
        "status": "WAITING_PAY",  # WAITING_PAY / COMPLETED / CANCELLED / PAYMENT_EXCEPTION
        "original_end_date": "", "new_end_date": "", "renew_days": 0,
        "original_days": 0, "new_total_days": 0,
        "quoted_amount": 0.0, "pricing_snapshot": [],
        "out_trade_no": "", "trade_no": "", "trade_status": "",
        "paid_at": None, "completed_at": None, "cancelled_at": None,
        "failure_reason": "", "raw_query": {},
    },
    id_type="str",
)

# 订单备注（仅后台工作人员可见；独立表，按 order_id 反查）
# 追加式审计日志：每条备注都是一条独立、不可变的记录，天然记录
#   「每一次修改 + 修改人 + 修改时间」。订单列表展示最新一条，详情弹窗展示全部。
# created_at 由 BaseRepository 自动写入，即为「修改时间」。
order_note_repo = SqliteRepository(
    DB_PATH, "order_notes",
    default_fields={
        "order_id": "",          # 关联订单 id（str）
        "content": "",           # 备注正文
        "staff_id": None,        # 修改人（工作人员）id
        "staff_username": "",    # 修改人账号（落库快照，避免员工改名后追溯不到）
        "staff_real_name": "",   # 修改人姓名（落库快照）
    },
)

# 支付宝回调日志（int 自增；硬删除清空）
notify_log_repo = SqliteRepository(
    DB_PATH, "notify_logs",
    default_fields={
        "channel": "", "verified": False, "business_ok": False,
        "duplicate": False, "note": "", "params": {}, "raw_body": "",
        "ts": 0,
    },
)

# 管理后台工作人员
staff_repo = SqliteRepository(
    DB_PATH, "staffs",
    default_fields={
        "username": "",
        "real_name": "",
        "password_hash": "",
        "role": "operator",     # admin | operator
        "last_login_at": None,
    },
)

# 收藏（user_id + product_id 唯一）；created_at 由 BaseRepository 自动写入
favorite_repo = SqliteRepository(
    DB_PATH, "favorites",
    default_fields={
        "user_id": "",
        "product_id": 0,
    },
)

# 分享行为流水（按需做统计/反作弊；channel 自由文本：alipay / link / poster ...）
share_log_repo = SqliteRepository(
    DB_PATH, "share_logs",
    default_fields={
        "user_id": "",
        "product_id": 0,
        "channel": "alipay",
        "ua": "",
    },
)

# 优惠券模板（管理后台维护；满减券：满 threshold 减 discount）
# total_quantity = 0 表示不限量；start_at / end_at 为 unix 秒时间戳，0/None 表示不限
coupon_repo = SqliteRepository(
    DB_PATH, "coupons",
    default_fields={
        "name": "",
        "threshold": 0.0,
        "discount": 0.0,
        "status": "on",        # on | off
        "start_at": 0,
        "end_at": 0,
        "total_quantity": 0,
        "claimed_quantity": 0,
        "per_user_limit": 1,   # 每用户最多领取数量；0 表示不限
        "remark": "",
    },
)

# 用户领取的优惠券实例（一张领一份；用掉则 status=used + 写入 order_id）
user_coupon_repo = SqliteRepository(
    DB_PATH, "user_coupons",
    default_fields={
        "user_id": "",
        "coupon_id": 0,
        "name": "",
        "threshold": 0.0,
        "discount": 0.0,
        "status": "unused",    # unused | used | expired
        "start_at": 0,
        "end_at": 0,
        "order_id": "",
        "claimed_at": 0,
        "used_at": 0,
    },
)

# 客服中心 - 常见问题（int 自增；sort 越小越靠前）
faq_repo = SqliteRepository(
    DB_PATH, "faqs",
    default_fields={
        "q":    "",   # 问题
        "a":    "",   # 答案（支持换行 \n）
        "sort": 0,    # 排序权重（小在前）
    },
)


# ============ 启动入口 ============

def init_seeds() -> None:
    """空表 → 种子数据；有数据 → 跳过。"""
    # 先尝试从老 JSON 文件迁移（一次性，迁完不再读 JSON）
    _migrate_legacy_json()

    banner_repo.seed(BANNERS_SEED)
    category_repo.seed(CATEGORIES_SEED)
    product_repo.seed(PRODUCTS_SEED)
    address_repo.seed(ADDRESSES_SEED)
    user_repo.seed(USERS_SEED)
    order_repo.seed(ORDERS_SEED)
    staff_repo.seed(STAFFS_SEED)
    faq_repo.seed(FAQS_SEED)

    # 老数据里 comments 是 product payload 的内联数组，迁到独立 comments 表
    _migrate_inline_comments()
    # 历史订单没有 freeze_amount 字段，按"押金 + 租金"（之前硬编码逻辑）回填
    _backfill_order_freeze_amount()
    # 历史 FAQ 文案升级（仅匹配老种子原文时才动，已被运营编辑过的不动）
    _upgrade_faq_texts()
    # 单一数据源改造：给还没有 SKU 的存量商品补建「标准版」
    _backfill_default_skus()


def _backfill_default_skus() -> None:
    """把商品级的价格/押金/库存搬到 SKU 层，保证「每个商品至少一个 SKU」这条不变式。

    幂等：只处理一个 SKU 都没有的商品，所以重启多少次都只补一次；
    运营后来自己加的 SKU 也不会被这里覆盖。
    """
    made = 0
    for p in product_repo.list():
        if ensure_default_sku(p):
            made += 1
    if made:
        print(f"[migrate] skus: 已为 {made} 个商品补建默认 SKU（{DEFAULT_SKU_NAME}）", flush=True)


def _backfill_order_freeze_amount() -> None:
    """历史订单没有 freeze_amount 字段，按"押金 + 租金"回填（与之前前端硬编码一致）。
    幂等：已有值的订单不动；下次启动也不会重复写。
    """
    import logging
    logger = logging.getLogger(__name__)
    fixed = 0
    for o in order_repo.list():
        try:
            cur = float(o.get("freeze_amount") or 0)
        except (TypeError, ValueError):
            cur = 0.0
        if cur > 0:
            continue
        deposit = float(o.get("deposit_freeze") or 0)
        rent    = float(o.get("amount") or 0)
        amt     = round(deposit + rent, 2)
        if amt <= 0:
            continue  # 数据完全空也跳过，没意义
        order_repo.update(o["id"], {
            "freeze_amount":        amt,
            "freeze_includes_rent": True,  # 无快照的历史订单仍按"押金+租金"
        })
        fixed += 1
    if fixed:
        logger.warning("order backfill: %d 个订单补 freeze_amount（押金+租金）", fixed)


# ============ FAQ 文案升级（指纹匹配，避免覆盖运营手动改过的内容） ============

# (question, old_answer, new_answer)
# 仅当 DB 里 a == old_answer 时才升级；说明运营没改过这条，可以安全替换。
_FAQ_TEXT_UPGRADES: list[tuple[str, str, str]] = [
    (
        "可以提前归还设备吗？",
        # 老种子原文（保持完全一致才匹配）
        "可以。订单进入「租赁中」后可在订单详情点击「我要归还」并填写寄回快递单号。"
        "租金按下单总额结算，提前归还差额不再退还。",
        # 新文案
        "可以。订单进入「租赁中」后可在订单详情点击「我要归还」并填写寄回快递单号。"
        "租金按下单总额结算，提前归还差额不再退还；"
        "但可联系客服，差额可在您下次租赁其他产品时减免对应费用。",
    ),
]


def _upgrade_faq_texts() -> None:
    """指纹比对升级 FAQ 文案。
    只在 DB 里的 q + a 与老种子完全一致时才替换 a；
    任何手工编辑过的（q 同但 a 不同）一律跳过，不破坏运营改动。
    """
    import logging
    logger = logging.getLogger(__name__)
    upgraded = 0
    items = faq_repo.list()
    for q, old_a, new_a in _FAQ_TEXT_UPGRADES:
        for f in items:
            if (f.get("q") or "") == q and (f.get("a") or "") == old_a:
                faq_repo.update(f["id"], {"a": new_a})
                upgraded += 1
                break  # 同 q 只升级一条
    if upgraded:
        logger.info("faq texts upgraded: %d entries", upgraded)


# ============ 老数据迁移 ============

_LEGACY_MAP = [
    ("banners",    banner_repo),
    ("categories", category_repo),
    ("addresses",  address_repo),
    ("products",   product_repo),
]


_OBSOLETE_PRODUCT_FIELDS = (
    "comments", "comments_total",
    "promo_label", "price", "activity",
    "discounts",  # 已废弃的"满 N 天 X 折"运营文案；price_tiers + price_curve 接管展示
)


def _migrate_inline_comments() -> None:
    """把产品 payload 里的内联 comments[] 迁出来到独立 comments 表，迁完清空原字段。

    幂等：对每个产品检查是否还有 payload.comments 这个非空数组；有则迁出；
    迁出后从 payload 移除（连同 comments_total / 其他废弃字段），再次启动就是 no-op。
    """
    for p in product_repo.list():
        inline = p.get("comments")
        if not inline or not isinstance(inline, list):
            if any(k in p for k in _OBSOLETE_PRODUCT_FIELDS):
                _drop_obsolete_product_fields(p["id"])
            continue

        moved = 0
        for c in inline:
            try:
                comment_repo.create({
                    "product_id": p["id"],
                    "user_id": "",
                    "user": (c.get("user") or "").strip() or "匿名用户",
                    "avatar_color": c.get("avatar_color")
                                    or "linear-gradient(135deg,#dde6f0,#aab8c8)",
                    "stars": int(c.get("stars") or 5),
                    "content": (c.get("content") or "").strip(),
                })
                moved += 1
            except Exception as e:
                print(f"[migrate-comments] product={p['id']}: 跳过一条 {e}", flush=True)

        _drop_obsolete_product_fields(p["id"])
        if moved:
            print(f"[migrate-comments] product={p['id']}: {moved} 条已迁入 comments 表",
                  flush=True)


def _drop_obsolete_product_fields(pid: int) -> None:
    """物理移除 payload 里已废弃的字段（update 写 None 只会把值置空，并不删 key）。"""
    cur = product_repo.get(pid)
    if not cur:
        return
    changed = False
    for k in _OBSOLETE_PRODUCT_FIELDS:
        if k in cur:
            del cur[k]
            changed = True
    if not changed:
        return
    # 用底层 SQL 重写 payload 字段，绕开 update 的 dict-merge 语义
    import json
    with product_repo._lock, product_repo._conn() as conn:
        conn.execute(
            f"UPDATE {product_repo.table} SET payload = ? WHERE id = ?",
            (json.dumps(cur, ensure_ascii=False), pid),
        )
        conn.commit()


def _migrate_legacy_json() -> None:
    """把老的 data/{banners,categories,addresses,products}.json 一次性导入 SQLite。

    导入策略：仅在对应 SQLite 表为空时执行；导入后给老 JSON 加 `.migrated` 后缀，
    避免下次启动重复导入，但保留文件以便人工回滚。
    """
    for name, repo in _LEGACY_MAP:
        # 已有数据就跳过
        if repo.count() > 0:
            continue
        legacy = os.path.join(DATA_DIR, f"{name}.json")
        if not os.path.exists(legacy):
            continue
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                payload = json.load(f)
            items = payload.get("items", [])
            if not items:
                continue
            for it in items:
                # 老 json 里 id 已存在，直接保留（int id 表用 INSERT 时也允许显式 id）
                repo.create({k: v for k, v in it.items() if k != "id" or repo.id_type == "str"})
            os.rename(legacy, legacy + ".migrated")
            print(f"[migrate] {name}: {len(items)} 条已从 JSON 迁入 SQLite", flush=True)
        except Exception as e:
            print(f"[migrate] {name}: 迁移失败 {e}", flush=True)
