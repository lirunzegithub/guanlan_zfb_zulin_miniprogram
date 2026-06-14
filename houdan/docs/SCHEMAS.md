# 数据模型字段设计

> 版本 v1。三类核心资源：**轮播图 banners** / **分类 categories** / **商品 products**。
> 当前底层使用 JSON 文件存储，存储中间层抽象了 Repository 接口，后续可无缝替换为 MySQL / PostgreSQL，无需改业务代码。

## 公共约定

- 所有 id 为整数自增，主键非业务字段
- 时间字段 `created_at` / `updated_at` 均为 Unix 秒级时间戳
- `enabled` 默认为 `true`；删除采用软删除（设为 `false`），后续 DB 化时易于审计
- `sort` 数字越小越靠前
- 字符串字段默认空串 `""`，集合默认空数组 `[]`
- 颜色 / 渐变 占位字段：`bg`, `cover_bg` 直接存 CSS（`linear-gradient(...)`），便于无图状态降级

---

## 1. 轮播图 banner

涵盖 **首页 hero 大图** + **三宫格 quick slot** + **后续可扩展的二级位**。
用 `position` 区分槽位，用 `slot` 决定槽位内顺序。

| 字段 | 类型 | 说明 |
|---|---|---|
| id            | int     | 自增主键 |
| position      | string  | `hero` / `quick` / `secondary`（未来可扩展） |
| slot          | int     | 在 position 内的位置序号（hero=0，quick=0/1/2） |
| title         | string  | 主文案（如 "Meta Quest 3"、"免押认证"） |
| subtitle      | string  | 副文案（如 "跳进游戏世界"、"点击此处"） |
| tag           | string  | 角标文字（如 `HOT`、`点击此处`），空表示无 |
| tag_style     | string  | `red` / `yellow` / `gradient` / `""`（控制角标视觉） |
| image_url     | string  | 主图 URL（OSS 路径或外链），空时降级到 `bg` |
| bg            | string  | CSS 背景占位（渐变/纯色），无图时使用 |
| link_type     | string  | `page` / `product` / `category` / `external` / `none` |
| link_value    | string  | 对应路径（如 `/pages/identity/identity`）、商品 id、分类 id、外链 url |
| start_at      | int?    | 上架时间（可空，空=立即生效） |
| end_at        | int?    | 下架时间（可空，空=永不下架） |
| enabled       | bool    | 是否上架，软删除 |
| sort          | int     | 兜底排序，主要排序还是 `slot` |
| created_at    | int     | |
| updated_at    | int     | |

---

## 2. 分类 category

支持多级分类（`parent_id` 默认 0 表示顶层）。与支付宝信用租的 `category` / `serviceId` 一一对应，便于后续真实接入。

| 字段 | 类型 | 说明 |
|---|---|---|
| id              | int     | |
| name            | string  | 显示名（"免押商品" / "VR一体机" 等） |
| parent_id       | int     | 0 = 顶层 |
| icon_url        | string  | 分类小图标 |
| cover_url       | string  | 分类页头图 |
| description     | string  | 分类描述 |
| sort            | int     | 排序 |
| enabled         | bool    | |
| service_id      | string  | 芝麻信用免押产品码（接支付宝时使用） |
| alipay_category | string  | 支付宝行业类目（如 `RENT_3C`、`RENT_DIGITAL`） |
| created_at      | int     | |
| updated_at      | int     | |

---

## 3. 商品 product

承载列表卡片 + 详情页所有展示。`shop` / `comments` 当前内嵌（DB 化后可拆表）。

| 字段 | 类型 | 说明 |
|---|---|---|
| id              | int     | |
| cat_id          | int     | 关联分类 id |
| name            | string  | 商品名 |
| subtitle        | string  | 副标题（"专业摄影 \| 操作便捷"） |
| tag             | string  | 列表卡片角标（"免押认证"） |
| cover_url       | string  | 主图 URL |
| cover_bg        | string  | 主图占位 CSS |
| amount          | int?    | 额度卡面额（500/1000 之类），普通商品填 0 |
| price_tiers     | array   | 分段租金（唯一价格数据源），`[{from, price}]`，首段 from===1 |
| min_price       | float   | 最低单价（由 price_tiers 派生，用于"X元/天起"） |
| rent_unit       | string  | 计租单位，默认 "天" |
| deposit_amount  | float   | 押金/冻结金额 |
| min_rent_days   | int     | 最少租天数 |
| max_rent_days   | int     | 最多租天数（0=不限） |
| stock           | int     | 库存数 |
| sales           | int     | 历史销量 |
| rented_count    | int     | 当前在租数 |
| credit          | bool    | 是否支持芝麻免押 |
| service_id      | string  | 芝麻服务码（落库时用） |
| tip             | string  | 顶部红色提示（"提前归还订单费用不退"） |
| intro           | string  | 富文本介绍（M 化） |
| shipping        | string  | 物流说明（"顺丰速运、上门自提"） |
| shipping_note   | string  | 发货时间长说明 |
| discounts       | array   | 阶梯折扣 `[{days, discount, factor}]` |
| price_curve     | array   | 长租折线图点位 `[{day, price}]`（由 price_tiers 派生） |
| rights          | array   | 权益 `[{key, label, icon}]` |
| real_shots      | array   | 实拍图缩略 `["url1", "url2"]` 或 CSS bg |
| spec_groups     | array   | SKU `[{name, options:["黑色","白色"]}]` |
| shop            | object  | 店铺信息（嵌入） |
| comments        | array   | 评论快照（用于列表展示，详情可走分页接口） |
| comments_total  | int     | 总评论数 |
| status          | string  | `on` / `off` / `draft` |
| enabled         | bool    | |
| sort            | int     | |
| created_at      | int     | |
| updated_at      | int     | |

### 内嵌 shop 对象

| 字段 | 类型 | 说明 |
|---|---|---|
| name             | string  | 店铺名 |
| tagline          | string  | 标语 ("靠口碑 交个朋友") |
| years            | int     | 经营年份 |
| score_desc       | float   | 描述评分 0-5 |
| score_service    | float   | 服务评分 |
| score_logistics  | float   | 物流评分 |
| cover_color      | string  | 海报 CSS 渐变 |

### 内嵌 comment 对象

| 字段 | 类型 | 说明 |
|---|---|---|
| id            | int    | |
| user          | string | 昵称 |
| stars         | int    | 1-5 |
| time          | string | 展示用时间 |
| content       | string | 文本内容 |
| avatar_color  | string | 头像占位 CSS |

---

## 存储中间层

- `app/storage/base.py` 定义 `BaseRepository`：`get / list / create / update / delete / find`
- `app/storage/json_store.py` 提供 `JsonRepository`：所有读写落到 `data/<name>.json`
- `app/storage/repos.py` 暴露全局单例：`banner_repo` / `category_repo` / `product_repo`

替换为数据库时：
1. 新增 `app/storage/sql_store.py` 实现 `BaseRepository` 同样接口
2. 在 `repos.py` 切换实现即可，业务路由（`app/routes/*`）零修改

### JSON 文件结构

```json
{
  "next_id": 13,
  "items": [
    { "id": 1, "...": "..." }
  ]
}
```
