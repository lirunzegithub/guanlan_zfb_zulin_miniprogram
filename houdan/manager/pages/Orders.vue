<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">订单管理</div>
      <div class="row" style="gap:8px">
        <input
          class="input kw-input"
          v-model.trim="keyword"
          placeholder="订单号 / 商品名 / 收货人 / 用户ID"
          @keyup.enter="doSearch"
        />
        <button class="btn btn-ghost btn-sm" @click="doSearch">搜索</button>
        <button class="btn btn-ghost btn-sm" @click="resetFilter" v-if="keyword || curTab !== 'all'">重置</button>
      </div>
    </div>

    <!-- 状态 Tab -->
    <div class="tabs">
      <div
        v-for="t in tabs"
        :key="t.key"
        :class="['tab', { active: curTab === t.key }]"
        @click="switchTab(t.key)"
      >
        {{ t.name }}
        <span class="tab-count" v-if="countOf(t.key) !== null">{{ countOf(t.key) }}</span>
      </div>
    </div>

    <table class="table order-table">
      <thead>
        <tr>
          <th style="width:120px">订单号</th>
          <th style="min-width:240px">商品</th>
          <th style="width:160px">用户</th>
          <th style="width:70px">年龄</th>
          <th style="width:80px">天数</th>
          <th style="width:110px">下单租金</th>
          <th style="width:110px">押金</th>
          <th style="width:170px">下单时间</th>
          <th style="width:180px">最新备注</th>
          <th style="width:90px">状态</th>
          <th style="width:200px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="o in list" :key="o.id">
          <td>
            <div class="oid">{{ o.id }}</div>
            <div class="muted" v-if="o.coupon_name">
              券：{{ o.coupon_name }} -¥{{ fmt(o.discount_amount) }}
            </div>
          </td>
          <td>
            <div class="prod">
              <div class="prod-cover">
                <img
                  v-if="o.product_cover"
                  :src="o.product_cover"
                  :alt="o.product_name"
                  @error="onCoverError"
                  loading="lazy"
                />
                <span v-else class="prod-cover-fallback">无图</span>
              </div>
              <div>
                <div class="prod-name">
                  {{ o.product_name || `#${o.product_id}` }}
                  <span v-if="o.sku_name" class="sku-tag" title="下单时选中的 SKU">{{ o.sku_name }}</span>
                </div>
                <div class="muted">¥{{ fmt(o.price_per_day) }} / {{ o.days }} 天</div>
                <span v-if="o.rent_platform" class="rent-plat" title="租赁平台（来自光影库存）">
                  {{ o.rent_platform }}
                </span>
                <span v-if="o.rent_remark" class="rent-remark" title="租赁备注（来自光影库存）">
                  {{ o.rent_remark }}
                </span>
              </div>
            </div>
          </td>
          <td>
            <div>{{ o.user_real_name || o.user_nickname || '匿名' }}</div>
            <div class="muted">{{ o.user_phone || o.user_id }}</div>
          </td>
          <td>
            <span v-if="o.user_age != null">{{ o.user_age }} 岁</span>
            <span v-else class="muted" title="该用户未提交身份证信息">-</span>
          </td>
          <td>{{ o.days }}</td>
          <td>
            <div>¥{{ fmt(o.amount) }}</div>
            <div class="muted strike" v-if="o.discount_amount && o.original_amount">
              ¥{{ fmt(o.original_amount) }}
            </div>
          </td>
          <td>
            <div>¥{{ fmt(o.deposit_freeze) }}</div>
            <div
              v-if="o.freeze_active"
              :class="['freeze-countdown', { warn: o.freeze_warn, expired: o.freeze_expired }]"
              :title="o.freeze_expired ? '支付宝已自动解冻该笔授权' : `授权将于 ${o.freeze_expire_at_text} 到期`"
            >
              <template v-if="o.freeze_expired">⚠ 授权已过期</template>
              <template v-else>授权剩 {{ o.freeze_days_left }} 天</template>
            </div>
          </td>
          <td>
            <div>{{ o.created_at_text }}</div>
          </td>
          <td>
            <div v-if="o.latest_note" class="note-cell" :title="o.latest_note.content">
              <div class="note-cell-text">{{ o.latest_note.content }}</div>
              <div class="muted small">
                {{ o.latest_note.staff_real_name || o.latest_note.staff_username || '—' }}
                · {{ o.latest_note.created_at_text }}
              </div>
            </div>
            <span v-else class="muted">—</span>
          </td>
          <td>
            <span :class="['tag', statusCls(o.status)]">{{ o.status_label }}</span>
          </td>
          <td>
            <button class="btn-link" @click="openDetail(o)">详情</button>
            <button
              v-if="o.status === 'send'"
              class="btn-link primary"
              @click="openShip(o)"
            >发货</button>
            <template v-if="o.status === 'pending_cancel' && !o.unfreeze_dispatched_at">
              <button class="btn-link primary" @click="approveCancel(o)">同意取消</button>
              <button class="btn-link" @click="rejectCancel(o)">驳回</button>
            </template>
            <span v-else-if="o.status === 'pending_cancel'" class="muted">已下发解冻，待支付宝通知</span>
            <template v-if="o.status === 'return_inspecting' && !o.unfreeze_dispatched_at">
              <button class="btn-link primary" @click="approveReturn(o)">核验通过</button>
              <button class="btn-link" @click="rejectReturn(o)">驳回</button>
            </template>
            <span v-else-if="o.status === 'return_inspecting'" class="muted">已下发解冻，待支付宝通知</span>
            <button
              v-if="['using', 'return', 'overdue'].includes(o.status)"
              class="btn-link"
              @click="openAdminReturnShip(o)"
            >代填寄回</button>
            <button
              v-for="act in actionsFor(o.status)"
              :key="act.to"
              class="btn-link"
              @click="quickTransition(o, act)"
            >{{ act.label }}</button>
            <button class="btn-link danger" @click="remove(o)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="11" class="empty">暂无订单</td></tr>
        <tr v-if="loading && !list.length"><td colspan="11" class="loading">加载中...</td></tr>
      </tbody>
    </table>

    <!-- 移动端：卡片式订单列表（与上方表格互斥显示） -->
    <div class="order-cards">
      <div v-if="loading && !list.length" class="loading">加载中...</div>
      <div v-else-if="!loading && !list.length" class="empty">暂无订单</div>
      <div v-for="o in list" :key="'m-' + o.id" class="order-card">
        <div class="oc-head">
          <span class="oid">{{ o.id }}</span>
          <span :class="['tag', statusCls(o.status)]">{{ o.status_label }}</span>
        </div>

        <div class="prod oc-prod">
          <div class="prod-cover">
            <img
              v-if="o.product_cover"
              :src="o.product_cover"
              :alt="o.product_name"
              @error="onCoverError"
              loading="lazy"
            />
            <span v-else class="prod-cover-fallback">无图</span>
          </div>
          <div class="oc-prod-info">
            <div class="prod-name">{{ o.product_name || `#${o.product_id}` }}</div>
            <div class="muted">¥{{ fmt(o.price_per_day) }} / {{ o.days }} 天</div>
          </div>
          <div class="oc-amount">
            <div>¥{{ fmt(o.amount) }}</div>
            <div class="muted strike small" v-if="o.discount_amount && o.original_amount">
              ¥{{ fmt(o.original_amount) }}
            </div>
          </div>
        </div>

        <div class="oc-rows">
          <div class="oc-row">
            <span class="oc-k">用户</span>
            <span>{{ o.user_real_name || o.user_nickname || '匿名' }}
              <span v-if="o.user_age != null" class="tag tag-gray">{{ o.user_age }} 岁</span>
              <span class="muted">{{ o.user_phone || o.user_id }}</span>
            </span>
          </div>
          <div class="oc-row">
            <span class="oc-k">押金</span>
            <span>
              ¥{{ fmt(o.deposit_freeze) }}
              <span
                v-if="o.freeze_active"
                :class="['freeze-countdown', { warn: o.freeze_warn, expired: o.freeze_expired }]"
                style="margin-left:6px"
              >
                <template v-if="o.freeze_expired">⚠ 授权已过期</template>
                <template v-else>授权剩 {{ o.freeze_days_left }} 天</template>
              </span>
            </span>
          </div>
          <div class="oc-row" v-if="o.rent_platform">
            <span class="oc-k">平台</span>
            <span><span class="rent-plat">{{ o.rent_platform }}</span></span>
          </div>
          <div class="oc-row">
            <span class="oc-k">下单</span>
            <span>{{ o.created_at_text }}</span>
          </div>
          <div class="oc-row" v-if="o.coupon_name">
            <span class="oc-k">优惠券</span>
            <span>{{ o.coupon_name }} <span class="muted">-¥{{ fmt(o.discount_amount) }}</span></span>
          </div>
          <div class="oc-row" v-if="o.latest_note">
            <span class="oc-k">备注</span>
            <span class="oc-note">
              {{ o.latest_note.content }}
              <span class="muted small">
                — {{ o.latest_note.staff_real_name || o.latest_note.staff_username || '—' }}
                · {{ o.latest_note.created_at_text }}
              </span>
            </span>
          </div>
        </div>

        <div class="oc-actions">
          <button class="btn-link" @click="openDetail(o)">详情</button>
          <button
            v-if="o.status === 'send'"
            class="btn-link primary"
            @click="openShip(o)"
          >发货</button>
          <template v-if="o.status === 'pending_cancel' && !o.unfreeze_dispatched_at">
            <button class="btn-link primary" @click="approveCancel(o)">同意取消</button>
            <button class="btn-link" @click="rejectCancel(o)">驳回</button>
          </template>
          <span v-else-if="o.status === 'pending_cancel'" class="muted">已下发解冻，待支付宝通知</span>
          <template v-if="o.status === 'return_inspecting' && !o.unfreeze_dispatched_at">
            <button class="btn-link primary" @click="approveReturn(o)">核验通过</button>
            <button class="btn-link" @click="rejectReturn(o)">驳回</button>
          </template>
          <span v-else-if="o.status === 'return_inspecting'" class="muted">已下发解冻，待支付宝通知</span>
          <button
            v-if="['using', 'return', 'overdue'].includes(o.status)"
            class="btn-link"
            @click="openAdminReturnShip(o)"
          >代填寄回</button>
          <button
            v-for="act in actionsFor(o.status)"
            :key="act.to"
            class="btn-link"
            @click="quickTransition(o, act)"
          >{{ act.label }}</button>
          <button class="btn-link danger" @click="remove(o)">删除</button>
        </div>
      </div>
    </div>

    <!-- 无限滚动：哨兵进视口即自动续加载，避免一次性渲染上千行 DOM 拖垮弱机器 -->
    <div class="feed-foot" ref="sentinel">
      <span v-if="loadingMore" class="feed-loading">加载中…</span>
      <span v-else-if="!loading && list.length && !hasMore" class="feed-end">
        没有更多了 · 共 {{ total }} 单
      </span>
    </div>
  </div>

  <!-- 详情弹窗 -->
  <div v-if="detail" class="modal-mask" @click.self="detail = null">
    <div class="modal" style="width:1080px; max-width:95vw; max-height:92vh">
      <div class="modal-h">订单详情 · {{ detail.id }}</div>
      <div class="modal-body">
        <div class="detail-grid">
          <div class="field">
            <div class="label">订单状态</div>
            <span :class="['tag', statusCls(detail.status)]">{{ detail.status_label }}</span>
          </div>
          <div class="field">
            <div class="label">下单时间</div>
            <div>{{ detail.created_at_text }}</div>
          </div>
          <div class="field">
            <div class="label">商品</div>
            <div>
              {{ detail.product_name }} <span class="muted">(#{{ detail.product_id }})</span>
              <span v-if="detail.sku_name" class="sku-tag">{{ detail.sku_name }}</span>
            </div>
            <div class="muted">¥{{ fmt(detail.price_per_day) }} × {{ detail.days }} 天</div>
            <div class="muted" v-if="detail.start_date && detail.end_date">
              租期：{{ detail.start_date }} 至 {{ detail.end_date }}
              <span v-if="detail.ship_days">（含物流 {{ detail.ship_days }} 天）</span>
            </div>
          </div>
          <div class="field">
            <div class="label">金额</div>
            <div>下单租金 <b>¥{{ fmt(detail.amount) }}</b></div>
            <div class="muted" v-if="detail.discount_amount">
              原价 ¥{{ fmt(detail.original_amount) }}，优惠 -¥{{ fmt(detail.discount_amount) }}
            </div>
            <div class="muted">押金（冻结）¥{{ fmt(detail.deposit_freeze) }}</div>
          </div>
          <div class="field" v-if="detail.freeze_active">
            <div class="label">押金授权倒计时</div>
            <div
              :class="['freeze-countdown-big', { warn: detail.freeze_warn, expired: detail.freeze_expired }]"
            >
              <template v-if="detail.freeze_expired">
                <b>已过期</b>
                <span class="muted small">（支付宝已自动解冻，无法再扣款）</span>
              </template>
              <template v-else>
                剩 <b>{{ detail.freeze_days_left }}</b> 天到期
                <span class="muted small">（{{ detail.freeze_expire_at_text }}）</span>
                <span v-if="detail.freeze_warn" class="tag tag-red" style="margin-left:6px">即将到期</span>
              </template>
            </div>
            <div class="muted small">
              芝麻免押授权有效期为 360 天，超过后支付宝自动解冻，商家无法再发起扣款。请在到期前完成订单结算或提前与用户协商处理。
            </div>
          </div>
          <div class="field">
            <div class="label">用户</div>
            <div>
              {{ detail.user_real_name || detail.user_nickname || '匿名' }}
              <span v-if="detail.user_age != null" class="tag tag-gray">{{ detail.user_age }} 岁</span>
              <span v-if="detail.user_verified" class="tag tag-green">已实名</span>
            </div>
            <div class="muted">{{ detail.user_phone || '-' }} · ID {{ detail.user_id }}</div>
          </div>
          <div class="field">
            <div class="label">收货</div>
            <div>{{ detail.address_snapshot?.receiver_name }} · {{ detail.address_snapshot?.receiver_phone }}</div>
            <div class="muted">{{ detail.address_snapshot?.full }}</div>
          </div>
          <!-- 用户下单时留的话（与下方「工作人员备注」不同，那个用户看不见） -->
          <div class="field" v-if="detail.user_remark">
            <div class="label">用户备注</div>
            <div class="user-remark">{{ detail.user_remark }}</div>
          </div>
          <div class="field" v-if="detail.coupon_name">
            <div class="label">优惠券</div>
            <div>{{ detail.coupon_name }}（满 ¥{{ fmt(detail.coupon_threshold) }} 减 ¥{{ fmt(detail.coupon_discount) }}）</div>
            <div class="muted" v-if="detail.coupon_grant">领取号 #{{ detail.coupon_grant.id }}，状态 {{ detail.coupon_grant.status }}</div>
          </div>
          <div class="field" v-if="detail.certify_id">
            <div class="label">人脸认证</div>
            <div class="muted mono">{{ detail.certify_id }}</div>
          </div>
          <div class="field" v-if="detail.logistics_no">
            <div class="label">物流信息</div>
            <div>
              <span class="tag tag-green" style="margin-right:6px">{{ detail.logistics_company_name }}</span>
              <span class="mono">{{ detail.logistics_no }}</span>
            </div>
            <div class="muted" v-if="detail.shipped_at_text">发货时间：{{ detail.shipped_at_text }}</div>
          </div>
          <div class="field" v-if="detail.item_huohao">
            <div class="label">绑定库存商品（光影）</div>
            <div class="inv-card" v-if="detail.item_snapshot && detail.item_snapshot.huohao">
              <div class="inv-cover">
                <img v-if="invCover(detail.item_snapshot)" :src="invCover(detail.item_snapshot)" @error="onCoverError" />
                <span v-else class="prod-cover-fallback">无图</span>
              </div>
              <div class="inv-info">
                <div class="inv-title">
                  {{ detail.item_snapshot.fenlei || '未知分类' }}
                  <span class="mono inv-huohao">{{ detail.item_snapshot.huohao }}</span>
                  <span v-if="detail.rent_platform" class="rent-plat" title="租赁平台（来自光影库存）">
                    {{ detail.rent_platform }}
                  </span>
                </div>
                <div class="inv-rows">
                  <span class="tag tag-green" v-if="detail.item_snapshot.zhuangtai">{{ detail.item_snapshot.zhuangtai }}</span>
                  <span class="tag" v-if="detail.item_snapshot.chengse">成色 {{ detail.item_snapshot.chengse }}</span>
                  <span class="tag" v-if="detail.item_snapshot.color">{{ detail.item_snapshot.color }}</span>
                  <span class="tag tag-gray" v-if="detail.item_snapshot.cangku">{{ detail.item_snapshot.cangku }}</span>
                </div>
                <div class="muted small" v-if="detail.item_snapshot.rukutime">入库时间：{{ detail.item_snapshot.rukutime }}</div>
                <div class="muted small" v-if="detail.item_snapshot.beizhu">备注：{{ detail.item_snapshot.beizhu }}</div>
                <div class="inv-wenti" v-if="detail.item_snapshot.wenti">⚠️ 问题：{{ detail.item_snapshot.wenti }}</div>

                <!-- 光影租赁记录（实时拉取，非发货快照） -->
                <div class="inv-rents" v-if="detail.item_snapshot.rent_records && detail.item_snapshot.rent_records.length">
                  <div class="inv-rents-title">租赁记录（实时 · 累计出租 {{ detail.item_snapshot.rent_count || 0 }} 次）</div>
                  <div class="inv-rent-row" v-for="r in detail.item_snapshot.rent_records" :key="r.id">
                    <span :class="['tag', r.action === 'ship_out' ? (r.pin ? 'tag-red' : 'tag-orange') : 'tag-gray']">{{ rentActionLabel(r.action) }}</span>
                    <span>{{ rentRecordText(r) || '—' }}</span>
                    <span class="muted">{{ r.create_time }}</span>
                    <span class="inv-rent-problem" v-if="r.inbound_problem">问题：{{ r.inbound_problem }}</span>
                    <span class="mono muted" v-if="r.ship_out_no">{{ r.ship_out_no }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else>
              <span class="mono">{{ detail.item_huohao }}</span>
              <span class="muted small" style="margin-left:6px" v-if="invCardLoading">光影库存加载中…</span>
              <span class="muted small" style="margin-left:6px" v-else>（光影库存未能实时加载，或货号不存在）</span>
            </div>
          </div>
          <div class="field" v-if="detail.return_logistics_no">
            <div class="label">用户寄回物流</div>
            <div>
              <span class="tag tag-orange" style="margin-right:6px">{{ detail.return_logistics_company_name }}</span>
              <span class="mono">{{ detail.return_logistics_no }}</span>
            </div>
            <div class="muted" v-if="detail.returned_at_text">用户提交时间：{{ detail.returned_at_text }}</div>
          </div>
          <div class="field" v-if="detail.sync_at_text || detail.sync_status">
            <div class="label">支付宝订单同步</div>
            <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
              <span :class="['tag', detail.sync_ok ? 'tag-green' : 'tag-red']">
                {{ detail.sync_ok ? '已同步' : '同步失败' }}
                <template v-if="detail.sync_status">· {{ detail.sync_status }}</template>
              </span>
              <span class="muted" v-if="detail.sync_at_text">{{ detail.sync_at_text }}</span>
              <button
                class="btn-link"
                :disabled="resyncing"
                @click="resync(detail)"
              >{{ resyncing ? '同步中…' : '重新同步' }}</button>
            </div>
            <div class="muted" v-if="!detail.sync_ok && detail.sync_err" style="margin-top:4px">
              失败原因：{{ detail.sync_err }}
            </div>
          </div>
        </div>

        <div class="divider"></div>

        <!-- 工作人员备注（独立审计日志，仅后台可见） -->
        <div class="field">
          <div class="label" style="display:flex;align-items:center;justify-content:space-between">
            <span>工作人员备注 <span class="muted small">（仅内部可见）</span></span>
            <button class="btn-link" style="font-weight:normal" @click="loadNotes">刷新</button>
          </div>

          <div class="note-add">
            <textarea
              class="input"
              style="width:100%;min-height:60px;resize:vertical"
              v-model.trim="noteInput"
              placeholder="填写本次备注（添加后将作为一条独立记录，留存修改人与时间，不可修改）"
              maxlength="1000"
            ></textarea>
            <div class="row" style="justify-content:flex-end;margin-top:6px">
              <button
                class="btn btn-sm"
                :disabled="!noteInput || noteSubmitting"
                @click="submitNote"
              >{{ noteSubmitting ? '添加中…' : '添加备注' }}</button>
            </div>
          </div>

          <div v-if="notesLoading" class="muted">加载中…</div>
          <div v-else-if="!notes.length" class="muted">暂无备注</div>
          <ul v-else class="note-list">
            <li v-for="n in notes" :key="n.id" class="note-item">
              <div class="note-item-content">{{ n.content }}</div>
              <div class="note-item-meta muted small">
                <span>{{ n.staff_real_name || n.staff_username || '未知' }}</span>
                <span v-if="n.staff_username && n.staff_real_name" class="mono">（{{ n.staff_username }}）</span>
                <span>· {{ n.created_at_text }}</span>
              </div>
            </li>
          </ul>
        </div>

        <div class="divider"></div>

        <!-- 支付宝授权资金明细（alipay.fund.auth.operation.detail.query，固定查 FREEZE 冻结）-->
        <div class="field">
          <div class="label" style="display:flex;align-items:center;justify-content:space-between">
            <span>支付宝预授权明细</span>
            <button class="btn-link" style="font-weight:normal" @click="loadAlipayDetail">刷新</button>
          </div>
          <div v-if="alipayLoading" class="muted">查询中…</div>
          <div v-else-if="!alipay" class="muted">—</div>
          <div v-else-if="!alipay.found" class="alipay-fail">
            <div class="alipay-fail-headline">{{ failHeadline(alipay, detail) }}</div>
            <div class="muted" style="margin-top:4px">
              <span v-if="alipay.sub_code" class="tag tag-orange" style="margin-right:6px">{{ alipay.sub_code }}</span>
              <span>{{ alipay.reason || alipay.sub_msg || alipay.msg || '' }}</span>
            </div>
          </div>
          <div v-else class="alipay-grid">
            <div class="alipay-cell">
              <span class="alipay-k">支付方式</span>
              <span :class="['tag', alipay.is_credit_auth ? 'tag-green' : 'tag-orange']">
                {{ alipay.is_credit_auth ? '芝麻信用免押 (CREDIT_AUTH)' : '资金冻结' }}
              </span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">授权单状态</span>
              <span class="mono">{{ alipay.order_status || '-' }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">本笔操作</span>
              <span class="mono">{{ alipay.operation_type }} · {{ alipay.status }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">本笔金额</span>
              <span>¥{{ fmt(alipay.amount) }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">累计冻结</span>
              <span>¥{{ fmt(alipay.total_freeze_amount) }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">当前剩余冻结</span>
              <span>¥{{ fmt(alipay.rest_amount) }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">累计支付</span>
              <span>¥{{ fmt(alipay.total_pay_amount) }}</span>
            </div>
            <div class="alipay-cell" v-if="alipay.is_credit_auth">
              <span class="alipay-k">累计冻结信用</span>
              <span>¥{{ fmt(alipay.total_freeze_credit_amount) }}</span>
            </div>
            <div class="alipay-cell" v-if="alipay.is_credit_auth">
              <span class="alipay-k">累计冻结自有</span>
              <span>¥{{ fmt(alipay.total_freeze_fund_amount) }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">支付宝授权号</span>
              <span class="mono small">{{ alipay.auth_no || '-' }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">操作流水号</span>
              <span class="mono small">{{ alipay.operation_id || '-' }}</span>
            </div>
            <div class="alipay-cell">
              <span class="alipay-k">付款方</span>
              <span class="muted">{{ alipay.payer_logon_id || alipay.payer_user_id || '-' }}</span>
            </div>
            <div class="alipay-cell" style="grid-column: 1 / -1">
              <span class="alipay-k">创建时间</span>
              <span class="muted">{{ alipay.gmt_create || '-' }}</span>
              <span class="muted" style="margin-left:18px" v-if="alipay.gmt_trans">账务时间：{{ alipay.gmt_trans }}</span>
            </div>
          </div>
        </div>

        <div class="divider"></div>

        <!-- 预授权扣款（信用免押 方案 A） -->
        <div class="field">
          <div class="label" style="display:flex;align-items:center;justify-content:space-between">
            <span>预授权扣款</span>
            <span class="row" style="gap:8px;font-weight:normal">
              <button class="btn-link" @click="loadCharges">刷新</button>
              <button class="btn-link primary" @click="openChargeForm">+ 发起扣款</button>
            </span>
          </div>

          <!-- 发起扣款表单（折叠） -->
          <div v-if="chargeForm.show" class="charge-form">
            <div class="cf-row">
              <label>扣款金额（元）</label>
              <input class="input" type="number" min="0.01" step="0.01" v-model.number="chargeForm.amount" />
            </div>
            <div class="cf-row">
              <label>扣款原因</label>
              <select class="select" v-model="chargeForm.reason_type">
                <option value="" disabled>请选择扣款原因</option>
                <option v-for="r in chargeReasonTypes" :key="r.value" :value="r.value">{{ r.label }}</option>
              </select>
            </div>
            <div class="cf-row">
              <label>具体说明</label>
              <input
                class="input"
                type="text"
                v-model.trim="chargeForm.reason_detail"
                :disabled="!chargeForm.reason_type"
                :placeholder="chargeForm.reason_type ? '请填写本次扣款的具体说明（如：屏幕碎裂 / 超期 5 天 等）' : '请先选择扣款原因'"
                maxlength="100"
              />
            </div>
            <div class="cf-row" v-if="chargeForm.reason_type">
              <label>扣款标题</label>
              <div class="muted small mono" style="word-break:break-all">{{ chargeSubjectPreview }}</div>
            </div>
            <div class="cf-row">
              <label>授权确认模式</label>
              <select class="select" v-model="chargeForm.auth_confirm_mode">
                <option value="NOT_COMPLETE">NOT_COMPLETE 扣后继续冻结剩余</option>
                <option value="COMPLETE" :disabled="!canUseComplete">
                  COMPLETE 扣后解冻剩余（最后一笔用）
                </option>
              </select>
            </div>
            <div class="cf-row" v-if="chargeForm.auth_confirm_mode === 'COMPLETE' && !canUseComplete">
              <div class="muted small" style="color:#c0260b">
                ⚠ 「扣后解冻剩余」仅在订单为「核验中」且用户已提交退回物流单号时可用；
                当前订单为「{{ statusLabel[detail.status] || detail.status }}」<span v-if="!detail.return_logistics_no">、且尚未收到用户寄回快递</span>。
              </div>
            </div>
            <div class="cf-row">
              <div class="muted small">
                <template v-if="detail.freeze_includes_rent !== false">
                  本订单冻结金额：押金 ¥{{ fmt(detail.deposit_freeze) }} + 租金 ¥{{ fmt(detail.amount) }} = ¥{{ fmt(detail.freeze_amount || (Number(detail.deposit_freeze || 0) + Number(detail.amount || 0))) }}（押金+租金模式）
                </template>
                <template v-else>
                  本订单冻结金额：仅押金 ¥{{ fmt(detail.freeze_amount || detail.deposit_freeze) }}（仅押金模式；租金独立扣款）
                </template>
                <br>
                授权号：<code class="mono small">{{ detail.alipay_auth_no || '（订单尚未完成免押授权）' }}</code>
              </div>
            </div>
            <div class="cf-actions">
              <button class="btn btn-ghost" @click="cancelChargeForm">取消</button>
              <button class="btn" :disabled="!canSubmitCharge || chargeSubmitting" @click="submitCharge">
                {{ chargeSubmitting ? '发起中…' : '确认扣款' }}
              </button>
            </div>
          </div>

          <!-- 扣款流水列表 -->
          <div v-if="chargesLoading" class="muted">加载中…</div>
          <div v-else-if="!charges.length" class="muted">尚无扣款记录</div>
          <table v-else class="charge-table">
            <thead>
              <tr>
                <th style="width:160px">时间</th>
                <th style="width:90px">金额</th>
                <th style="width:100px">状态</th>
                <th>说明</th>
                <th style="width:180px">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in charges" :key="t.id">
                <td><span class="muted small">{{ t.created_at_text }}</span></td>
                <td>
                  <div>¥{{ fmt(t.amount) }}</div>
                  <div class="muted small" v-if="(t.refunded_amount || 0) > 0">
                    已退 ¥{{ fmt(t.refunded_amount) }}
                  </div>
                </td>
                <td><span :class="['tag', tradeStatusCls(t.status)]">{{ t.status_label }}</span></td>
                <td>
                  <div class="ellipsis">{{ t.subject }}</div>
                  <div class="trade-ids">
                    <div class="tid-row">
                      <span class="tid-k">商户单号</span>
                      <code class="mono small">{{ t.id }}</code>
                      <button class="btn-link tid-copy" @click="copyText(t.id, '商户单号')">复制</button>
                    </div>
                    <div class="tid-row" v-if="t.trade_no">
                      <span class="tid-k">支付宝单号</span>
                      <code class="mono small">{{ t.trade_no }}</code>
                      <button class="btn-link tid-copy" @click="copyText(t.trade_no, '支付宝单号')">复制</button>
                    </div>
                  </div>
                  <div class="muted small" v-if="t.fail_code">{{ t.fail_code }} · {{ t.fail_msg }}</div>
                  <!-- 退款历史展开 -->
                  <div v-if="(t.refunds || []).length" class="refund-history">
                    <div v-for="r in t.refunds" :key="r.out_request_no" class="refund-item">
                      <span :class="['tag', refundStatusCls(r.status)]">{{ refundStatusLabel(r.status) }}</span>
                      <span>¥{{ fmt(r.amount) }}</span>
                      <span class="muted small">{{ r.created_at_text }}</span>
                      <span class="muted small" v-if="r.reason">· {{ r.reason }}</span>
                      <button
                        v-if="r.status !== 'REFUND_SUCCESS'"
                        class="btn-link"
                        @click="onQueryRefund(t, r)"
                        :disabled="chargeBusy === t.id + ':' + r.out_request_no"
                      >查询</button>
                      <span class="muted small" v-if="r.fail_code">{{ r.fail_code }} · {{ r.fail_msg }}</span>
                    </div>
                  </div>
                </td>
                <td>
                  <button class="btn-link" @click="onQueryCharge(t)" :disabled="chargeBusy === t.id">刷新</button>
                  <button v-if="canCloseTrade(t)" class="btn-link danger" @click="onCloseCharge(t)" :disabled="chargeBusy === t.id">取消</button>
                  <button
                    v-if="canRefundTrade(t)"
                    class="btn-link"
                    @click="onRefundCharge(t)"
                    :disabled="chargeBusy === t.id"
                  >退款</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="divider"></div>

        <div class="field">
          <div class="label">变更状态</div>
          <div class="row" style="gap:8px">
            <select class="select" style="width:180px" v-model="editStatus">
              <option v-for="(name, k) in statusLabel" :key="k" :value="k">{{ name }}</option>
            </select>
            <label class="muted">
              <input type="checkbox" v-model="forceStatus" /> 强制修改（跳过流转校验）
            </label>
          </div>
          <div class="muted" style="margin-top:6px">
            当前：{{ detail.status_label }}。建议按白名单流转，强改会绕过状态机校验。
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="detail = null">关闭</button>
        <button class="btn" :disabled="saving || editStatus === detail.status" @click="saveStatus">
          {{ saving ? '保存中…' : '保存修改' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 发货弹窗 -->
  <div v-if="shipForm" class="modal-mask" @click.self="closeShip">
    <div class="modal" style="max-width:520px">
      <div class="modal-h">发货 · {{ shipForm.oid }}</div>
      <div class="modal-body">
        <div class="field" v-if="shipForm.userRemark">
          <div class="label">用户备注</div>
          <div class="user-remark">{{ shipForm.userRemark }}</div>
        </div>
        <div class="field">
          <div class="label">运单号</div>
          <input
            class="input"
            style="width:100%"
            v-model.trim="shipForm.no"
            placeholder="粘贴或扫描运单号，自动识别快递公司"
            autofocus
            @input="onWaybillInput"
          />
          <div class="muted" style="margin-top:6px;min-height:20px">
            <template v-if="shipForm.identifying">识别中…</template>
            <template v-else-if="!shipForm.no">支持顺丰、京东；其他快递暂未接入</template>
            <template v-else-if="shipForm.detectedCode === 'unknown'">
              <span class="tag tag-orange">未识别</span>
              请在下方手动选择快递公司
            </template>
            <template v-else>
              已识别为
              <span class="tag tag-green">{{ shipForm.detectedName }}</span>
            </template>
          </div>
        </div>

        <!-- 仅在自动识别失败时显示下拉，让用户兜底选择 -->
        <div class="field" v-if="shipForm.detectedCode === 'unknown'">
          <div class="label">快递公司（手动选择）</div>
          <select class="select" style="width:240px" v-model="shipForm.manualCode">
            <option value="">请选择</option>
            <option v-for="c in couriers" :key="c.code" :value="c.code">{{ c.name }}</option>
          </select>
        </div>

        <!-- 光影库存货号：选填/必填由后台设置决定 -->
        <div class="field">
          <div class="label">货号{{ uiCfg.ship_huohao_required ? '（必填）' : '（选填）' }}</div>
          <input
            class="input"
            style="width:100%"
            v-model.trim="shipForm.huohao"
            placeholder="填写光影库存系统货号，自动加载商品信息"
            @input="onHuohaoInput"
          />
          <div class="muted" style="margin-top:6px;min-height:20px">
            <template v-if="shipForm.itemLoading">查询中…</template>
            <template v-else-if="!shipForm.huohao"></template>
            <template v-else-if="shipForm.itemStatus === 'not_found'">
              <span class="tag tag-orange">未找到</span> {{ shipForm.itemMsg }}
            </template>
            <template v-else-if="shipForm.itemStatus === 'not_configured'">
              <span class="tag tag-gray">未对接</span> 未配置光影特权Token（后台设置中配置后可自动加载商品卡片）
            </template>
            <template v-else-if="shipForm.itemStatus === 'error'">
              <span class="tag tag-red">查询失败</span> {{ shipForm.itemMsg }}
            </template>
          </div>

          <!-- 商品详情卡片：供操作人确认 -->
          <div class="inv-card" v-if="shipForm.itemStatus === 'ok' && shipForm.item">
            <div class="inv-cover">
              <img v-if="invCover(shipForm.item)" :src="invCover(shipForm.item)" @error="onCoverError" />
              <span v-else class="prod-cover-fallback">无图</span>
            </div>
            <div class="inv-info">
              <div class="inv-title">
                {{ shipForm.item.fenlei || '未知分类' }}
                <span class="mono inv-huohao">{{ shipForm.item.huohao }}</span>
              </div>
              <div class="inv-rows">
                <span class="tag tag-green" v-if="shipForm.item.zhuangtai">{{ shipForm.item.zhuangtai }}</span>
                <span class="tag" v-if="shipForm.item.chengse">成色 {{ shipForm.item.chengse }}</span>
                <span class="tag" v-if="shipForm.item.color">{{ shipForm.item.color }}</span>
                <span class="tag tag-gray" v-if="shipForm.item.cangku">{{ shipForm.item.cangku }}</span>
              </div>
              <div class="muted small" v-if="shipForm.item.rukutime">入库时间：{{ shipForm.item.rukutime }}</div>
              <div class="muted small" v-if="shipForm.item.beizhu">备注：{{ shipForm.item.beizhu }}</div>
              <div class="inv-wenti" v-if="shipForm.item.wenti">⚠️ 问题：{{ shipForm.item.wenti }}</div>

              <!-- 当前在租警示：防止一机两租 -->
              <div class="inv-renting" v-if="shipForm.item.current_rent">
                🔴 该设备当前在租{{ shipForm.item.current_rent.rent_platform ? '（' + shipForm.item.current_rent.rent_platform + '）' : '' }}<template v-if="shipForm.item.current_rent.rent_end">，预计 {{ shipForm.item.current_rent.rent_end }} 到期</template>，请核实后再发货！
              </div>

              <!-- 光影租赁记录 -->
              <div class="inv-rents" v-if="shipForm.item.rent_records && shipForm.item.rent_records.length">
                <div class="inv-rents-title">租赁记录（累计出租 {{ shipForm.item.rent_count || 0 }} 次）</div>
                <div class="inv-rent-row" v-for="r in shipForm.item.rent_records" :key="r.id">
                  <span :class="['tag', r.action === 'ship_out' ? (r.pin ? 'tag-red' : 'tag-orange') : 'tag-gray']">{{ rentActionLabel(r.action) }}</span>
                  <span>{{ rentRecordText(r) || '—' }}</span>
                  <span class="muted">{{ r.create_time }}</span>
                  <span class="inv-rent-problem" v-if="r.inbound_problem">问题：{{ r.inbound_problem }}</span>
                  <span
                    class="inv-rent-waybill"
                    v-if="r.ship_out_no"
                    :title="'点击把运单号 ' + r.ship_out_no + ' 填入上方输入框'"
                    @click="fillWaybillFromRent(r)"
                  >{{ r.ship_out_no }} ⤴ 填入</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="field">
          <div class="muted">
            提交后订单将自动流转为「待收货」，发货时间记为当前时刻。
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="closeShip" :disabled="shipForm.submitting">取消</button>
        <button class="btn" :disabled="!canSubmitShip || shipForm.submitting" @click="submitShip">
          {{ shipForm.submitting ? '提交中…' : '确认发货' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 代用户填写寄回信息弹窗（using / return / overdue → return_inspecting） -->
  <div v-if="adminReturnForm" class="modal-mask" @click.self="closeAdminReturnShip">
    <div class="modal" style="max-width:520px">
      <div class="modal-h">代用户填写寄回信息 · {{ adminReturnForm.oid }}</div>
      <div class="modal-body">
        <div class="field">
          <div class="muted small" style="margin-bottom:10px">
            适用于用户私聊客服处理归还的场景。提交后订单进入「核验中」，
            后续仍走商家「核验通过」→ 自动解冻押金的标准链路。
          </div>
        </div>
        <div class="field">
          <div class="label">快递公司</div>
          <select class="select" style="width:240px" v-model="adminReturnForm.company">
            <option value="">请选择</option>
            <option v-for="c in couriers" :key="c.code" :value="c.code">{{ c.name }}</option>
          </select>
        </div>
        <div class="field">
          <div class="label">运单号</div>
          <input
            class="input"
            style="width:100%"
            v-model.trim="adminReturnForm.no"
            placeholder="请输入用户提供的寄回运单号"
            autofocus
          />
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="closeAdminReturnShip" :disabled="adminReturnForm.submitting">取消</button>
        <button class="btn"
                :disabled="!adminReturnForm.company || !adminReturnForm.no || adminReturnForm.submitting"
                @click="submitAdminReturnShip">
          {{ adminReturnForm.submitting ? '提交中…' : '提交寄回信息' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, reactive, computed, inject, onMounted, onUnmounted, nextTick } = Vue;

const STATUS_LABEL = {
  audit:             '待免押',
  send:              '待发货',
  pending_cancel:    '取消审核中',
  recv:              '待收货',
  using:             '租赁中',
  return:            '待归还',
  overdue:           '已逾期',
  return_inspecting: '核验中',
  done:              '已完成',
  cancelled:         '已取消',
};

const TAGS_BY_STATUS = {
  audit:             'tag',
  send:              'tag-orange',
  pending_cancel:    'tag-red',
  recv:              'tag-orange',
  using:             'tag-green',
  return:            'tag',
  overdue:           'tag-red',
  return_inspecting: 'tag-orange',
  done:              'tag-gray',
  cancelled:         'tag-gray',
};

// 列表行的快捷操作：按当前状态展示一两个最常用的下一步动作
// pending_cancel / return_inspecting 走专用按钮（同意/驳回），不放进通用 QUICK_ACTIONS
const QUICK_ACTIONS = {
  audit:             [{ to: 'cancelled', label: '取消' }],
  send:              [{ to: 'cancelled', label: '取消' }],
  pending_cancel:    [],
  recv:              [{ to: 'using', label: '标记签收' }, { to: 'cancelled', label: '取消' }],
  using:             [{ to: 'return', label: '进入归还' }, { to: 'overdue', label: '标记逾期' }],
  return:            [{ to: 'done', label: '完成订单' }],
  overdue:           [{ to: 'return', label: '已归还' }, { to: 'done', label: '强制完成' }],
  return_inspecting: [],
  done:              [],
  cancelled:         [],
};

const TABS = [
  { key: 'all',               name: '全部' },
  { key: 'audit',             name: '待免押' },
  { key: 'send',              name: '待发货' },
  { key: 'pending_cancel',    name: '取消审核' },
  { key: 'recv',              name: '待收货' },
  { key: 'using',             name: '租赁中' },
  { key: 'return',            name: '待归还' },
  { key: 'overdue',           name: '已逾期' },
  { key: 'return_inspecting', name: '核验中' },
  { key: 'done',              name: '已完成' },
  { key: 'cancelled',         name: '已取消' },
];

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const loading = ref(true);
    const curTab = ref('all');
    const keyword = ref('');
    const statsCount = ref({});
    // 下滑无限加载：每次取一页 50 条 append 到 list，滑到底自动续。
    const page = ref(1);
    const pageSize = ref(50);
    const total = ref(0);
    const loadingMore = ref(false);           // 正在加载下一页
    const hasMore = computed(() => list.value.length < total.value);
    const sentinel = ref(null);               // 列表底部哨兵，进视口即触发续加载
    let io = null;                            // IntersectionObserver 实例

    const detail = ref(null);
    const invCardLoading = ref(false);   // 详情页光影卡片异步加载中标志
    const editStatus = ref('');
    const forceStatus = ref(false);
    const saving = ref(false);

    // 支付宝授权资金明细（每次打开订单详情自动查一次）
    const alipay = ref(null);
    const alipayLoading = ref(false);
    // 当前 UI 固定只查 FREEZE 冻结明细；UNFREEZE/PAY 已被「预授权扣款」等专用区块覆盖
    const ALIPAY_OP_TYPE = 'FREEZE';

    // 工作人员备注（独立审计日志）
    const notes = ref([]);
    const notesLoading = ref(false);
    const noteInput = ref('');
    const noteSubmitting = ref(false);

    // 预授权扣款（信用免押 方案 A）
    const charges = ref([]);
    const chargesLoading = ref(false);
    const chargeBusy = ref('');                      // 当前正在 query/close 的 out_trade_no
    const chargeForm = reactive({
      show: false,
      amount: 0,
      reason_type: '',     // 必选：RENT_SERVICE / OVERDUE_PENALTY / DAMAGE_LOSS / USER_CONFIRMED_OTHER
      reason_detail: '',   // 选填：操作员补充说明
      auth_confirm_mode: 'NOT_COMPLETE',
    });
    const chargeSubmitting = ref(false);

    // 扣款原因枚举：首次打开扣款表单时按需从后端拉
    const chargeReasonTypes = ref([]);
    const ensureChargeReasonTypes = async () => {
      if (chargeReasonTypes.value.length) return;
      try {
        const r = await api.chargeReasonTypes();
        chargeReasonTypes.value = r.list || [];
      } catch (e) { /* 静默：选项空时按钮自然不可用 */ }
    };

    // 最终传给支付宝的 subject 预览，逻辑与后端保持一致
    const chargeSubjectPreview = computed(() => {
      const item = chargeReasonTypes.value.find(x => x.value === chargeForm.reason_type);
      if (!item) return '';
      const tail = chargeForm.reason_detail || (detail.value?.product_name || '租赁');
      return `【${item.label}】${tail}`;
    });

    // COMPLETE（扣后解冻剩余）只允许在 return_inspecting + 用户已寄回 的订单上使用
    const canUseComplete = computed(() => {
      const d = detail.value;
      return !!(d && d.status === 'return_inspecting' && (d.return_logistics_no || '').trim());
    });

    const canSubmitCharge = computed(() => {
      const a = Number(chargeForm.amount) || 0;
      const base = a > 0 && !!chargeForm.reason_type && detail.value && (detail.value.alipay_auth_no || '');
      if (!base) return false;
      // COMPLETE 模式必须满足前置条件
      if (chargeForm.auth_confirm_mode === 'COMPLETE' && !canUseComplete.value) return false;
      return true;
    });

    const TRADE_STATUS_CLS = {
      INIT:           'tag',
      WAIT_BUYER_PAY: 'tag-orange',
      TRADE_SUCCESS:  'tag-green',
      TRADE_FINISHED: 'tag-gray',
      TRADE_CLOSED:   'tag-gray',
      FAILED:         'tag-red',
    };
    const tradeStatusCls = (s) => TRADE_STATUS_CLS[s] || 'tag';
    const canCloseTrade  = (t) => ['INIT', 'WAIT_BUYER_PAY'].includes(t.status);

    // 发货弹窗：shipForm = null 表示未打开
    const shipForm = ref(null);
    const couriers = ref([]);   // 下拉用，仅在自动识别失败时展示
    let identifyTimer = null;   // onInput 防抖句柄

    // 光影库存对接：UI 标志（货号必填开关、是否已配置 token）
    const uiCfg = ref({ ship_huohao_required: false, inventory_sync_configured: false });
    let uiCfgLoaded = false;
    let huohaoTimer = null;     // 货号输入防抖句柄

    const loadUiCfg = async () => {
      if (uiCfgLoaded) return;
      try {
        uiCfg.value = await api.uiConfig();
        uiCfgLoaded = true;
      } catch (e) { /* 拉不到按默认（选填）处理，不阻塞发货 */ }
    };

    // 商品快照图片：pic / kaixiang_pics 都是逗号分隔的 URL 串，合并去重
    const invPics = (item) => {
      if (!item) return [];
      const raw = [item.pic || '', item.kaixiang_pics || ''].join(',');
      return [...new Set(raw.split(',').map(s => s.trim()).filter(Boolean))];
    };
    const invCover = (item) => invPics(item)[0] || '';

    // 光影租赁记录：action → 中文
    const rentActionLabel = (a) => ({ ship_out: '出租', inbound: '回库' }[a] || a || '');
    // 点击租赁记录上的出库单号 → 填入运单号输入框并触发快递识别
    const fillWaybillFromRent = (r) => {
      if (!shipForm.value || !(r && r.ship_out_no)) return;
      shipForm.value.no = String(r.ship_out_no).trim();
      onWaybillInput();
    };
    // 单条记录的展示行：平台 / 起止 / 租客 / 回库问题 拼成一句
    const rentRecordText = (r) => {
      const parts = [];
      if (r.rent_platform) parts.push(r.rent_platform);
      // 光影发货时通常只录到期日、不录起租日，故仅显示到期日避免出现 "? ~"
      if (r.rent_end) parts.push(`${r.rent_end} 到期`);
      else if (r.rent_start) parts.push(`${r.rent_start} 起租`);
      if (r.renter_name) parts.push(r.renter_name);
      if (r.rent_remark) parts.push(r.rent_remark);
      return parts.join(' · ');
    };

    // 支付宝商家订单同步重试 loading
    const resyncing = ref(false);

    const fmt = (v) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return '0';
      return n.toFixed(2).replace(/\.00$/, '').replace(/(\.\d)0$/, '$1');
    };

    // <img> 加载失败兜底：把 src 清空，CSS 自然显示 fallback。
    // 同时把节点替换成占位文案，避免浏览器默认的「破图标」更难看。
    const onCoverError = (e) => {
      const img = e.target;
      if (!img || img.dataset.fallback === '1') return;
      img.dataset.fallback = '1';
      img.replaceWith(Object.assign(document.createElement('span'), {
        className: 'prod-cover-fallback',
        textContent: '加载失败',
      }));
    };

    const statusCls = (s) => TAGS_BY_STATUS[s] || 'tag-gray';

    const countOf = (key) => {
      if (key === 'all') return statsCount.value.total ?? null;
      const m = statsCount.value.by_status || {};
      return m[key] ?? null;
    };

    const actionsFor = (status) => QUICK_ACTIONS[status] || [];

    const fetchStats = async () => {
      try { statsCount.value = await api.list('orders/stats'); }
      catch (e) { /* 角标拉不到不阻塞主流程 */ }
    };

    // 当前的服务端过滤条件（tab + 关键词）。搜索/筛选一律由后端执行，
    // 前端只渲染服务端返回的结果，绝不在本地对 list 做二次过滤。
    const baseParams = () => {
      const p = {};
      if (curTab.value !== 'all') p.status = curTab.value;
      if (keyword.value) p.keyword = keyword.value;
      return p;
    };

    // 首屏 / 重新筛选：回到第 1 页，整屏 loading，替换 list。
    const fetch = async () => {
      loading.value = true;
      page.value = 1;
      try {
        const r = await api.list('orders', { ...baseParams(), page: 1, size: pageSize.value });
        list.value = r.list || [];
        total.value = r.total || 0;
      } catch (e) { alert(e.message || '加载失败'); }
      finally { loading.value = false; }
      fetchStats();
      fillRentInfo(list.value);   // 异步补光影平台/备注，不阻塞列表显示
    };

    // 下滑续加载：取下一页 append。用 id 去重，避免期间有新订单插入导致的错位重复。
    const loadMore = async () => {
      if (loadingMore.value || loading.value || !hasMore.value) return;
      loadingMore.value = true;
      const next = page.value + 1;
      try {
        const r = await api.list('orders', { ...baseParams(), page: next, size: pageSize.value });
        const seen = new Set(list.value.map(o => o.id));
        const fresh = (r.list || []).filter(o => !seen.has(o.id));
        list.value.push(...fresh);
        total.value = r.total || 0;
        page.value = next;
        fillRentInfo(fresh);      // 只给新增的行补光影数据
      } catch (e) { /* 失败不前进页码，下次滑动可重试 */ }
      finally { loadingMore.value = false; }
    };

    // 就地刷新已加载的全部行（发货/状态变更/删除等操作后调用）：一次性重拉
    // 「当前已展示的条数」，不改变滚动位置，不把用户弹回顶部。
    const reload = async () => {
      const size = Math.min(500, Math.max(pageSize.value, list.value.length));
      try {
        const r = await api.list('orders', { ...baseParams(), page: 1, size });
        list.value = r.list || [];
        total.value = r.total || 0;
        page.value = Math.max(1, Math.ceil(list.value.length / pageSize.value));
      } catch (e) { /* 保留现有列表 */ }
      fetchStats();
      fillRentInfo(list.value);
    };

    // 搜索：条件变了从头筛（服务端执行），回第 1 页
    const doSearch = () => { fetch(); };

    // 异步补数：把指定行的货号发给后端拉光影，回来后把平台/备注填进各行。
    // 只请求 rows 涉及的货号（续加载时就只补新行），但更新一律遍历 list.value，
    // 通过响应式代理写入才能触发行重渲染。光影慢/挂只影响这两个标签的出现速度。
    const fillRentInfo = async (rows) => {
      const target = rows && rows.length ? rows : list.value;
      const huohaos = [...new Set(
        target.map(o => (o.item_huohao || '').trim()).filter(Boolean)
      )];
      if (!huohaos.length) return;
      try {
        const cards = await api.inventoryCards(huohaos);   // { 货号: {..., rent_platform, rent_remark} }
        for (const o of list.value) {
          const c = cards[(o.item_huohao || '').trim()];
          if (c) { o.rent_platform = c.rent_platform || ''; o.rent_remark = c.rent_remark || ''; }
        }
      } catch (e) { /* 光影不可用不影响列表 */ }
    };

    const switchTab = (k) => {
      if (curTab.value === k) return;
      curTab.value = k;
      fetch();               // fetch 内部会回到第 1 页
    };

    const resetFilter = () => {
      keyword.value = '';
      curTab.value = 'all';
      fetch();
    };

    const openDetail = async (o) => {
      try {
        const full = await api.get('orders', o.id);
        detail.value = full;
        editStatus.value = full.status;
        forceStatus.value = false;
        // 并行拉支付宝预授权明细 / 扣款流水 —— 不阻塞详情主体渲染
        alipay.value = null;
        charges.value = [];
        chargeForm.show = false;
        notes.value = [];
        noteInput.value = '';
        loadAlipayDetail();
        loadCharges();
        loadNotes();
        loadInvCard();   // 异步拉光影商品卡片+租赁记录，不阻塞详情主体渲染
      } catch (e) { alert(e.message || '加载失败'); }
    };

    // 详情页异步补数：按本单货号拉光影卡片，填入 item_snapshot + 平台/备注。
    // 光影慢/挂只影响卡片出现速度，详情主体（订单信息）早已渲染。
    const loadInvCard = async () => {
      const d = detail.value;
      const hh = (d && (d.item_huohao || '')).trim();
      if (!hh) return;
      invCardLoading.value = true;
      try {
        const cards = await api.inventoryCards([hh]);
        const c = cards[hh];
        if (detail.value !== d) return;   // 已切换到别的单则丢弃
        if (c) {
          detail.value = {
            ...detail.value,
            item_snapshot: c,
            rent_platform: c.rent_platform || '',
            rent_remark: c.rent_remark || '',
          };
        }
      } catch (e) { /* 光影不可用不影响详情 */ }
      finally { if (detail.value === d) invCardLoading.value = false; }
    };

    // ── 工作人员备注 ──
    const loadNotes = async () => {
      if (!detail.value) return;
      notesLoading.value = true;
      try {
        const r = await api.listOrderNotes(detail.value.id);
        notes.value = r.list || [];
      } catch (e) {
        // 静默失败，不打断主流程
      } finally {
        notesLoading.value = false;
      }
    };

    const submitNote = async () => {
      if (!detail.value || !noteInput.value) return;
      noteSubmitting.value = true;
      try {
        const created = await api.addOrderNote(detail.value.id, noteInput.value);
        noteInput.value = '';
        // 新备注插到最前面（与后端「最新在前」一致），同步刷新详情/列表的最新备注
        notes.value = [created, ...notes.value];
        detail.value = { ...detail.value, latest_note: created };
        const row = list.value.find(x => x.id === detail.value.id);
        if (row) row.latest_note = created;
      } catch (e) { alert(e.message || '添加失败'); }
      finally { noteSubmitting.value = false; }
    };

    // ── 预授权扣款（方案 A）相关 ──
    const loadCharges = async () => {
      if (!detail.value) return;
      chargesLoading.value = true;
      try {
        const r = await api.listCharges(detail.value.id);
        charges.value = r.list || [];
      } catch (e) {
        // 静默失败，不打断主流程
      } finally {
        chargesLoading.value = false;
      }
    };

    const openChargeForm = () => {
      if (!detail.value) return;
      if (!detail.value.alipay_auth_no) {
        alert('订单尚未完成免押授权（缺 auth_no），无法发起扣款。\n用户必须先完成 freeze 授权才有可扣额度。');
        return;
      }
      chargeForm.show = true;
      chargeForm.amount = Number(detail.value.amount || 0);  // 默认按订单租金
      chargeForm.reason_type = '';
      chargeForm.reason_detail = '';
      chargeForm.auth_confirm_mode = 'NOT_COMPLETE';
      ensureChargeReasonTypes();
    };
    const cancelChargeForm = () => {
      chargeForm.show = false;
    };
    const submitCharge = async () => {
      if (!canSubmitCharge.value || chargeSubmitting.value) return;
      const confirmMsg =
        `确认对订单 ${detail.value.id} 发起扣款？\n\n` +
        `金额：¥${chargeForm.amount}\n` +
        `标题：${chargeSubjectPreview.value}\n` +
        `授权确认模式：${chargeForm.auth_confirm_mode}\n\n` +
        (chargeForm.auth_confirm_mode === 'COMPLETE'
          ? '⚠️ COMPLETE 会在本次扣款后立即解冻剩余冻结金额，无法再发起后续扣款。'
          : '本次扣款后剩余金额仍冻结，可继续发起后续扣款。');
      if (!confirm(confirmMsg)) return;

      chargeSubmitting.value = true;
      try {
        await api.createCharge(detail.value.id, {
          amount: chargeForm.amount,
          reason_type: chargeForm.reason_type,
          reason_detail: chargeForm.reason_detail,
          auth_confirm_mode: chargeForm.auth_confirm_mode,
        });
        chargeForm.show = false;
        await loadCharges();
      } catch (e) {
        alert(e.message || '发起扣款失败');
      } finally {
        chargeSubmitting.value = false;
      }
    };
    const onQueryCharge = async (t) => {
      chargeBusy.value = t.id;
      try {
        await api.queryCharge(t.id);
        await loadCharges();
      } catch (e) { alert(e.message || '刷新失败'); }
      finally { chargeBusy.value = ''; }
    };
    const onCloseCharge = async (t) => {
      if (!confirm(`关闭扣款 ${t.id}？\n仅未成功的扣款可关；已成功的请走退款流程。`)) return;
      chargeBusy.value = t.id;
      try {
        await api.closeCharge(t.id);
        await loadCharges();
      } catch (e) { alert(e.message || '关闭失败'); }
      finally { chargeBusy.value = ''; }
    };

    const copyText = async (text, label = '内容') => {
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
      } catch (e) {
        // 老浏览器兜底
        const ta = document.createElement('textarea');
        ta.value = text; document.body.appendChild(ta);
        ta.select(); document.execCommand('copy');
        document.body.removeChild(ta);
      }
      // 用一个非阻塞 toast 风格的提示，免得 alert 弹窗打断流
      const tip = document.createElement('div');
      tip.textContent = `已复制${label}`;
      tip.style.cssText = 'position:fixed;left:50%;top:30px;transform:translateX(-50%);background:#1a1f2e;color:#fff;padding:8px 16px;border-radius:4px;font-size:13px;z-index:9999;';
      document.body.appendChild(tip);
      setTimeout(() => tip.remove(), 1200);
    };

    // ---- 退款 ----
    const canRefundTrade = (t) => {
      if (!t) return false;
      if (!['TRADE_SUCCESS', 'TRADE_FINISHED'].includes(t.status)) return false;
      // 仍有剩余可退金额
      return Number(t.refundable_amount || 0) > 0;
    };

    const REFUND_STATUS_LABEL = {
      INIT:            '已发起',
      SUBMITTED:       '受理中',
      REFUND_SUCCESS:  '退款成功',
      FAILED:          '退款失败',
    };
    const REFUND_STATUS_CLS = {
      INIT:            'tag-orange',
      SUBMITTED:       'tag-orange',
      REFUND_SUCCESS:  'tag-green',
      FAILED:          'tag-red',
    };
    const refundStatusLabel = (s) => REFUND_STATUS_LABEL[s] || (s || '-');
    const refundStatusCls   = (s) => REFUND_STATUS_CLS[s] || 'tag';

    const onRefundCharge = async (t) => {
      const refundable = Number(t.refundable_amount || 0);
      if (refundable <= 0) { alert('该扣款已无剩余可退'); return; }
      const amtStr = prompt(
        `对扣款 ${t.id} 发起退款\n剩余可退：¥${refundable.toFixed(2)}\n请输入本次退款金额（元）：`,
        refundable.toFixed(2),
      );
      if (amtStr === null) return;
      const amt = Number(amtStr);
      if (!(amt > 0) || amt > refundable + 1e-9) {
        alert(`金额非法或超出剩余可退（¥${refundable.toFixed(2)}）`);
        return;
      }
      const reason = prompt('退款理由（可选，会展示在用户支付宝账单详情里）：', '运营补退') || '';
      if (!confirm(`确认对 ${t.id} 退款 ¥${amt.toFixed(2)}？\n理由：${reason || '（无）'}`)) return;
      chargeBusy.value = t.id;
      try {
        const r = await api.refundCharge(t.id, { amount: amt, reason });
        await loadCharges();
        alert((r && r.msg) || '退款已下发');
      } catch (e) { alert(e.message || '退款失败'); }
      finally { chargeBusy.value = ''; }
    };

    const onQueryRefund = async (t, r) => {
      const key = t.id + ':' + r.out_request_no;
      chargeBusy.value = key;
      try {
        await api.queryRefund(t.id, r.out_request_no);
        await loadCharges();
      } catch (e) { alert(e.message || '查询失败'); }
      finally { chargeBusy.value = ''; }
    };

    const loadAlipayDetail = async () => {
      if (!detail.value) return;
      alipayLoading.value = true;
      try {
        alipay.value = await api.orderAlipayDetail(detail.value.id, ALIPAY_OP_TYPE);
      } catch (e) {
        alipay.value = { found: false, reason: e.message || '查询失败' };
      } finally {
        alipayLoading.value = false;
      }
    };

    // 对常见错误码做业务侧解读 —— 让管理员一眼看懂"为什么没数据"
    const failHeadline = (a, o) => {
      if (!a) return '';
      // 后端兜底（订单本地从未发起 freeze）
      if (a.reason && /未发起过/.test(a.reason)) {
        return '订单尚未发起过支付宝预授权';
      }
      const code = a.sub_code || '';
      const status = (o && o.status) || '';
      switch (code) {
        case 'AUTH_ORDER_NOT_EXIST':
          if (status === 'audit') {
            return '用户尚未在支付宝端完成预授权（已唤起过 freeze，但用户取消/被拒/未完成）';
          }
          return '阿里端订单已不存在（可能超时关闭或已结清）';
        case 'AUTH_OPERATION_NOT_EXIST':
          return '本次操作流水在阿里端不存在（参数 out_request_no / operation_id 不匹配）';
        case 'HAS_NO_PRIVILEGE':
          return '商户无权查看该订单（产品未签约或签约已过期）';
        case 'ACCESS_FORBIDDEN':
          return '应用无该接口调用权限（去开放平台核对芝麻免押产品状态）';
        case 'ILLEGAL_ARGUMENT':
          return '请求参数异常';
        case 'SYSTEM_ERROR':
          return '支付宝端系统繁忙，稍后重试';
      }
      return a.sub_msg || a.msg || '查询失败';
    };

    const saveStatus = async () => {
      if (!detail.value) return;
      saving.value = true;
      try {
        const updated = await api.update('orders', detail.value.id, {
          status: editStatus.value,
          force:  forceStatus.value,
        });
        detail.value = { ...detail.value, ...updated };
        await reload();
      } catch (e) { alert(e.message || '保存失败'); }
      finally { saving.value = false; }
    };

    // ---------- 发货 ----------
    const openShip = async (o) => {
      shipForm.value = {
        oid: o.id,
        // 用户下单备注：发货前必须看见（"周五后再发"这类要求只能在这一步照做）
        userRemark: o.user_remark || '',
        no: '',
        detectedCode: '',   // '' | 'SF' | 'JD' | 'unknown'
        detectedName: '',
        manualCode: '',
        identifying: false,
        submitting: false,
        // 光影库存货号 + 商品卡片加载状态
        huohao: '',
        itemLoading: false,
        itemStatus: '',     // '' | 'ok' | 'not_found' | 'not_configured' | 'error'
        item: null,
        itemMsg: '',
      };
      loadUiCfg();
      // 第一次打开时拉一次 couriers 列表（缓存到组件期）
      if (!couriers.value.length) {
        try {
          const r = await api.couriers();
          couriers.value = r.list || [];
        } catch (e) { /* 静默：unknown 兜底时再提示 */ }
      }
    };

    const closeShip = () => {
      if (shipForm.value?.submitting) return;
      shipForm.value = null;
      if (identifyTimer) { clearTimeout(identifyTimer); identifyTimer = null; }
      if (huohaoTimer) { clearTimeout(huohaoTimer); huohaoTimer = null; }
    };

    // 货号输入：防抖 500ms 调库存系统查商品卡片
    const onHuohaoInput = () => {
      const f = shipForm.value;
      if (!f) return;
      if (huohaoTimer) clearTimeout(huohaoTimer);
      const hh = (f.huohao || '').trim();
      f.item = null;
      f.itemStatus = '';
      f.itemMsg = '';
      if (!hh) { f.itemLoading = false; return; }
      f.itemLoading = true;
      huohaoTimer = setTimeout(async () => {
        const snap = shipForm.value;
        if (!snap || (snap.huohao || '').trim() !== hh) return;
        try {
          const r = await api.inventoryItem(hh);
          if (!shipForm.value || (shipForm.value.huohao || '').trim() !== hh) return;
          shipForm.value.itemStatus = r.lookup_status || 'error';
          shipForm.value.item = r.item || null;
          shipForm.value.itemMsg = r.message || '';
        } catch (e) {
          if (!shipForm.value || (shipForm.value.huohao || '').trim() !== hh) return;
          shipForm.value.itemStatus = 'error';
          shipForm.value.itemMsg = e.message || '查询失败';
        } finally {
          if (shipForm.value && (shipForm.value.huohao || '').trim() === hh) {
            shipForm.value.itemLoading = false;
          }
        }
      }, 500);
    };

    // 运单号输入：防抖 300ms 调一次识别接口
    const onWaybillInput = () => {
      if (!shipForm.value) return;
      if (identifyTimer) clearTimeout(identifyTimer);
      const no = shipForm.value.no || '';
      if (!no) {
        shipForm.value.detectedCode = '';
        shipForm.value.detectedName = '';
        return;
      }
      shipForm.value.identifying = true;
      identifyTimer = setTimeout(async () => {
        // 异步期间用户可能关掉弹窗或又改了 no，这里都做一次防御
        const snap = shipForm.value;
        if (!snap || snap.no !== no) return;
        try {
          const r = await api.identifyCourier(no);
          if (!shipForm.value || shipForm.value.no !== no) return;
          shipForm.value.detectedCode = r.code || 'unknown';
          shipForm.value.detectedName = r.name || '';
          // 自动识别成功时清掉手动选择，避免歧义
          if (r.code !== 'unknown') shipForm.value.manualCode = '';
        } catch (e) {
          if (!shipForm.value || shipForm.value.no !== no) return;
          shipForm.value.detectedCode = 'unknown';
          shipForm.value.detectedName = '';
        } finally {
          if (shipForm.value && shipForm.value.no === no) {
            shipForm.value.identifying = false;
          }
        }
      }, 300);
    };

    const canSubmitShip = computed(() => {
      const f = shipForm.value;
      if (!f || !f.no || f.identifying) return false;
      // 后台设置「货号必填」时未填不可提交
      if (uiCfg.value.ship_huohao_required && !(f.huohao || '').trim()) return false;
      // 识别成功 → 直接可提；识别失败 → 必须手动选了
      if (f.detectedCode && f.detectedCode !== 'unknown') return true;
      return !!f.manualCode;
    });

    // 手动重试支付宝商家订单同步（成功/失败都会刷新详情卡片状态）
    const resync = async (o) => {
      if (!o || resyncing.value) return;
      resyncing.value = true;
      try {
        const r = await api.resyncOrder(o.id);
        // 后端无论成功失败都返回 code=0，详情字段会带上最新 sync_ok / sync_err
        detail.value = { ...detail.value, ...r };
        // 列表里那一行 sync_ok 也会变；顺便刷新一下
        await reload();
      } catch (e) {
        alert(e.message || '同步失败');
      } finally {
        resyncing.value = false;
      }
    };

    const submitShip = async () => {
      const f = shipForm.value;
      if (!f || !canSubmitShip.value) return;
      f.submitting = true;
      try {
        const body = { logistics_no: f.no };
        if (f.detectedCode === 'unknown' && f.manualCode) {
          body.logistics_company = f.manualCode;
        }
        if ((f.huohao || '').trim()) {
          body.huohao = f.huohao.trim();
        }
        await api.shipOrder(f.oid, body);
        shipForm.value = null;
        await reload();
      } catch (e) {
        alert(e.message || '发货失败');
      } finally {
        if (shipForm.value) shipForm.value.submitting = false;
      }
    };

    const quickTransition = async (o, act) => {
      // 「取消」单独走带解冻的专用接口：直接改状态到 cancelled 不会解冻押金，
      // 会把用户预授权冻结额一直卡到到期，故必须走 admin-cancel。
      if (act.to === 'cancelled') return forceCancel(o);
      if (!confirm(`确认将订单 ${o.id} 流转为「${STATUS_LABEL[act.to]}」？`)) return;
      try {
        await api.update('orders', o.id, { status: act.to });
        await reload();
      } catch (e) { alert(e.message || '操作失败'); }
    };

    // 后台主动取消订单：先弹窗确认（会解冻客户押金），再调 admin-cancel。
    const forceCancel = async (o) => {
      const frozen = Number(o.freeze_amount || o.deposit_freeze || 0);
      const amountLine = frozen > 0 ? `\n本单已冻结押金约 ¥${frozen.toFixed(2)}，取消后将下发解冻。` : '';
      if (!confirm(
        `⚠️ 取消订单 ${o.id}\n\n` +
        `取消会解冻客户押金，请务必确认该订单尚未发货 / 已收回货物后再操作！${amountLine}\n\n` +
        `确认继续取消并解冻押金？`
      )) return;
      try {
        await api.adminForceCancel(o.id);
        await reload();
      } catch (e) { alert(e.message || '取消失败'); }
    };

    // pending_cancel 专用：同意取消（调 unfreeze 解冻）/ 驳回（回 send）
    // 同意后订单仍停在 pending_cancel（status_label=解冻中），等支付宝异步 notify
    // 回来才会推到 cancelled；商家这里只触发解冻请求下发。
    const approveCancel = async (o) => {
      const userMsg = o.cancel_reason ? `用户填写理由：${o.cancel_reason}\n\n` : '';
      if (!confirm(`${userMsg}同意取消订单 ${o.id}？\n将下发解冻请求；支付宝异步确认后订单会自动置为已取消。`)) return;
      try {
        await api.approveOrderCancel(o.id);
        await reload();
      } catch (e) { alert(e.message || '同意失败'); }
    };
    const rejectCancel = async (o) => {
      const reason = prompt('驳回理由（可选，会让用户看到）：', '已发货');
      if (reason === null) return;  // 用户点了取消按钮
      try {
        await api.rejectOrderCancel(o.id, reason);
        await reload();
      } catch (e) { alert(e.message || '驳回失败'); }
    };

    // return_inspecting 专用：核验通过（调 unfreeze 全额解冻）/ 驳回（回 return）
    // 通过后订单停在 return_inspecting（status_label=解冻中），等异步 notify
    // 回来才推到 done；商家这里只触发解冻请求下发。
    const approveReturn = async (o) => {
      const courier = o.return_logistics_company_name || o.return_logistics_company || '-';
      const no = o.return_logistics_no || '-';
      if (!confirm(
        `确认核验通过订单 ${o.id}？\n` +
        `快递：${courier}  运单：${no}\n` +
        `将下发解冻请求；支付宝异步确认后订单会自动置为已完成。`,
      )) return;
      try {
        await api.approveOrderReturn(o.id);
        await reload();
      } catch (e) { alert(e.message || '核验失败'); }
    };
    const rejectReturn = async (o) => {
      const reason = prompt('驳回理由（可选，会让用户看到）：', '未收到包裹');
      if (reason === null) return;
      try {
        await api.rejectOrderReturn(o.id, reason);
        await reload();
      } catch (e) { alert(e.message || '驳回失败'); }
    };

    // 客服代用户填写寄回快递信息（using/return/overdue → return_inspecting）
    const adminReturnForm = ref(null);
    const openAdminReturnShip = async (o) => {
      adminReturnForm.value = {
        oid:        o.id,
        company:    '',
        no:         '',
        submitting: false,
      };
      // 复用与发货弹窗同源的快递公司列表
      if (!couriers.value.length) {
        try {
          const r = await api.couriers();
          couriers.value = r.list || [];
        } catch (e) { /* 静默 */ }
      }
    };
    const closeAdminReturnShip = () => {
      if (adminReturnForm.value?.submitting) return;
      adminReturnForm.value = null;
    };
    const submitAdminReturnShip = async () => {
      const f = adminReturnForm.value;
      if (!f || !f.company || !f.no) return;
      f.submitting = true;
      try {
        await api.submitOrderReturnShip(f.oid, {
          logistics_company: f.company,
          logistics_no:      f.no,
        });
        adminReturnForm.value = null;
        await reload();
      } catch (e) {
        alert(e.message || '提交失败');
      } finally {
        if (adminReturnForm.value) adminReturnForm.value.submitting = false;
      }
    };

    const remove = async (o) => {
      const safeDelete = o.status === 'done' || o.status === 'cancelled';
      const tip = safeDelete
        ? `确认删除订单 ${o.id}？`
        : `订单 ${o.id} 还在进行中，强制删除会丢失退押凭据，确定？`;
      if (!confirm(tip)) return;
      try {
        await api.remove('orders', o.id, safeDelete ? null : { force: true });
        await reload();
      } catch (e) { alert(e.message || '删除失败'); }
    };

    // 首屏加载 + 装无限滚动观察器：哨兵进视口（提前 300px）就续加载下一页
    onMounted(async () => {
      await fetch();
      await nextTick();
      if (sentinel.value && 'IntersectionObserver' in window) {
        io = new IntersectionObserver((entries) => {
          if (entries.some(e => e.isIntersecting)) loadMore();
        }, { rootMargin: '300px' });
        io.observe(sentinel.value);
      }
    });
    onUnmounted(() => { if (io) { io.disconnect(); io = null; } });
    return {
      list, loading, tabs: TABS, curTab, keyword, statusLabel: STATUS_LABEL,
      detail, invCardLoading, editStatus, forceStatus, saving,
      notes, notesLoading, noteInput, noteSubmitting, loadNotes, submitNote,
      alipay, alipayLoading, loadAlipayDetail, failHeadline,
      charges, chargesLoading, chargeBusy, chargeForm, chargeSubmitting,
      chargeReasonTypes, chargeSubjectPreview,
      canSubmitCharge, canUseComplete, tradeStatusCls, canCloseTrade,
      loadCharges, openChargeForm, cancelChargeForm, submitCharge,
      onQueryCharge, onCloseCharge, copyText,
      canRefundTrade, refundStatusLabel, refundStatusCls, onRefundCharge, onQueryRefund,
      shipForm, couriers, canSubmitShip,
      openShip, closeShip, onWaybillInput, submitShip,
      uiCfg, onHuohaoInput, invPics, invCover, rentActionLabel, rentRecordText, fillWaybillFromRent,
      resyncing, resync,
      approveCancel, rejectCancel,
      approveReturn, rejectReturn,
      adminReturnForm, openAdminReturnShip, closeAdminReturnShip, submitAdminReturnShip,
      fmt, onCoverError, statusCls, countOf, actionsFor,
      fetch, doSearch, switchTab, resetFilter, openDetail, saveStatus, quickTransition, remove,
      total, loadingMore, hasMore, sentinel,
    };
  },
};
</script>

<style scoped>
/* 无限滚动底部：哨兵 + 状态文案 */
.feed-foot {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 44px;
  padding: 12px 0 4px;
}
.feed-loading { font-size: 13px; color: var(--text-2, #6b7280); }
.feed-loading::before {
  content: '';
  display: inline-block;
  width: 12px; height: 12px;
  margin-right: 8px;
  border: 2px solid var(--line, #d6dbe3);
  border-top-color: var(--primary, #2b7cff);
  border-radius: 50%;
  vertical-align: -2px;
  animation: feed-spin 0.7s linear infinite;
}
@keyframes feed-spin { to { transform: rotate(360deg); } }
.feed-end { font-size: 12px; color: var(--text-3, #9aa4b2); }

.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 12px;
  overflow-x: auto;
}
.tab {
  padding: 9px 14px;
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  transition: 0.15s;
}
.tab:hover { color: var(--primary); }
.tab.active {
  color: var(--primary);
  border-bottom-color: var(--primary);
  font-weight: 600;
}
.tab-count {
  display: inline-block;
  margin-left: 5px;
  padding: 0 6px;
  border-radius: 999px;
  background: #eef1f6;
  color: var(--text-2);
  font-size: 11px;
  font-weight: 500;
}
.tab.active .tab-count { background: var(--primary-soft); color: var(--primary); }

.oid { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }

/* 列表「最新备注」单元格：正文最多两行截断 */
.note-cell-text {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.4;
  color: var(--text);
}

/* 用户下单备注：商家需要照做的话，给个浅黄底让它在 grid 里跳出来 */
.user-remark {
  background: #fff8e6;
  border-left: 3px solid var(--warn, #ff8a00);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 详情弹窗「工作人员备注」子区域 */
.note-add { margin-bottom: 10px; }
.note-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 240px;
  overflow-y: auto;
}
.note-item {
  padding: 8px 0;
  border-bottom: 1px dashed var(--line);
}
.note-item:last-child { border-bottom: none; }
.note-item-content {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
.note-item-meta { margin-top: 4px; }
.note-item-meta .mono { margin: 0 2px; }

.prod { display: flex; align-items: center; gap: 10px; }
.prod > div:last-child { flex: 1; min-width: 0; }
.prod-cover {
  width: 44px; height: 44px;
  border-radius: 6px;
  background-color: #eef1f6;
  flex-shrink: 0;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.prod-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.prod-cover-fallback {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1;
  text-align: center;
  padding: 0 4px;
}
.prod-name { font-weight: 500; line-height: 1.45; word-break: break-word; }
/* 订单里的 SKU 标签：下单时选中的 SKU 名快照 */
.sku-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 7px;
  font-size: 12px;
  line-height: 1.5;
  font-weight: 500;
  color: #2f5d9e;
  background: #eef4ff;
  border: 1px solid #cfe0ff;
  border-radius: 4px;
  vertical-align: middle;
}

.rent-plat {
  display: inline-block;
  margin-top: 4px;
  padding: 1px 7px;
  font-size: 12px;
  line-height: 1.5;
  color: #7c4d00;
  background: #fff3e0;
  border: 1px solid #ffe0b2;
  border-radius: 4px;
  white-space: nowrap;
}

.rent-remark {
  display: inline-block;
  margin-top: 4px;
  margin-left: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: #6b7280;
}

.strike { text-decoration: line-through; }

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 24px;
}
.detail-grid .field { margin-bottom: 0; }
.divider {
  height: 1px;
  background: var(--line);
  margin: 18px 0;
}
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 12px; }
.mono.small { font-size: 11px; word-break: break-all; }

.alipay-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 18px;
  margin-top: 6px;
  font-size: 12px;
}
.alipay-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 10px;
  background: #f7f9fc;
  border-radius: 4px;
  border: 1px solid #eef1f6;
}
.alipay-k {
  color: #6b7280;
  font-size: 11px;
}

/* ---------- 订单列表：搜索框 / 移动端卡片 ---------- */
.kw-input { width: 240px; }
.order-cards { display: none; }

.order-card {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  background: #fff;
}
.oc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}
.oc-prod { align-items: flex-start; }
.oc-prod-info { flex: 1; min-width: 0; }
.oc-prod-info .prod-name { word-break: break-all; }
.oc-amount {
  text-align: right;
  font-weight: 600;
  flex-shrink: 0;
}
.oc-rows {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.oc-row { display: flex; gap: 8px; }
.oc-k {
  width: 44px;
  flex-shrink: 0;
  color: var(--text-3);
}
.oc-note { word-break: break-word; line-height: 1.5; }
.oc-actions {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--line);
  display: flex;
  flex-wrap: wrap;
  gap: 2px 4px;
}
.oc-actions .btn-link { padding: 6px 8px; }
.oc-actions .muted { padding: 6px 0; font-size: 12px; }

@media (max-width: 768px) {
  .detail-grid { grid-template-columns: 1fr; gap: 10px; }
  .alipay-grid { grid-template-columns: 1fr 1fr; }
  .charge-form .cf-row { flex-wrap: wrap; }
  .charge-form .cf-row > label { width: 100%; }

  /* 列表切换：隐藏宽表格，显示卡片 */
  .order-table { display: none; }
  .order-cards { display: flex; flex-direction: column; gap: 10px; }

  /* 工具条垂直堆叠：标题一行，搜索框 + 按钮一行 */
  .toolbar { flex-direction: column; align-items: stretch; gap: 8px; }
  .toolbar > .row { width: 100%; flex-wrap: nowrap; }
  .kw-input { flex: 1; width: auto; min-width: 0; }
}

.alipay-fail {
  padding: 10px 12px;
  background: #fff8ee;
  border-left: 3px solid #f0a955;
  border-radius: 4px;
  margin-top: 6px;
}
.alipay-fail-headline {
  color: #8a4f00;
  font-size: 13px;
  line-height: 1.5;
}

/* 发货按钮：在一排操作里加粗以突出主操作 */
.btn-link.primary { font-weight: 600; }

/* 押金授权 360 天倒计时：列表小字 + 详情大字两套样式 */
.freeze-countdown {
  margin-top: 2px;
  font-size: 12px;
  color: #8a8f99;
  line-height: 1.4;
}
.freeze-countdown.warn {
  color: #d4380d;
  font-weight: 600;
}
.freeze-countdown.expired {
  color: #b0b3ba;
}
.freeze-countdown-big {
  font-size: 14px;
  color: #4a5060;
  line-height: 1.6;
}
.freeze-countdown-big.warn {
  color: #d4380d;
  font-weight: 600;
}
.freeze-countdown-big.warn b {
  font-size: 18px;
}
.freeze-countdown-big.expired {
  color: #b0b3ba;
}

/* 预授权扣款（信用免押 方案 A） */
.charge-form {
  margin: 8px 0 14px;
  padding: 12px 14px;
  background: #f7f9fc;
  border-radius: 4px;
  border: 1px solid #eef1f6;
}
.charge-form .cf-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.charge-form .cf-row > label {
  width: 110px;
  font-size: 13px;
  color: #4a5060;
  flex-shrink: 0;
}
.charge-form .cf-row > .input,
.charge-form .cf-row > .select {
  flex: 1;
  height: 32px;
  font-size: 13px;
  padding: 0 8px;
}
.charge-form .cf-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}

.charge-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-top: 6px;
}
.charge-table th {
  text-align: left;
  padding: 6px 8px;
  background: #f7f9fc;
  color: #6b7280;
  font-weight: 500;
  border-bottom: 1px solid #eef1f6;
}
.charge-table td {
  padding: 8px;
  border-bottom: 1px dashed #eef1f6;
  vertical-align: top;
}
.small { font-size: 11px; }

/* 商户单号 / 支付宝单号 展示 */
.trade-ids {
  margin-top: 4px;
  display: flex; flex-direction: column; gap: 2px;
}
.tid-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 11px;
}
.tid-k {
  display: inline-block;
  min-width: 64px;
  color: #6b7280;
}
.tid-row code {
  font-size: 11px;
  background: #f3f5f9;
  padding: 1px 6px;
  border-radius: 3px;
  color: #1a1f2e;
}
.tid-copy {
  font-size: 11px !important;
  padding: 0 4px;
}

/* 退款历史展开 */
.refund-history {
  margin-top: 6px;
  padding: 6px 8px;
  background: #f7faff;
  border-left: 2px solid #4d8dff;
  border-radius: 0 4px 4px 0;
}
.refund-item {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 2px 0;
  font-size: 12px;
}
.refund-item + .refund-item { border-top: 1px dashed #dde3ec; padding-top: 4px; margin-top: 4px; }

/* 光影库存商品卡片（发货弹窗 + 订单详情共用） */
.inv-card {
  display: flex;
  gap: 12px;
  margin-top: 8px;
  padding: 10px;
  border: 1px solid #e2e8f2;
  border-radius: 8px;
  background: #f8fafd;
}
.inv-cover {
  width: 72px; height: 72px; flex-shrink: 0;
  border-radius: 6px; overflow: hidden;
  background: #eef1f6;
  display: flex; align-items: center; justify-content: center;
}
.inv-cover img { width: 100%; height: 100%; object-fit: cover; }
.inv-info {
  display: flex; flex-direction: column; gap: 4px;
  min-width: 0; font-size: 12px;
}
.inv-title { font-size: 13px; font-weight: 600; color: #1a1f2e; }
.inv-huohao {
  font-size: 11px;
  background: #eef3fb;
  color: #2f5fae;
  padding: 1px 6px;
  border-radius: 3px;
  margin-left: 4px;
}
.inv-rows { display: flex; gap: 4px; flex-wrap: wrap; }
.inv-wenti {
  margin-top: 2px;
  padding: 4px 8px;
  background: #fdecea;
  color: #c0260b;
  border-radius: 4px;
  font-size: 12px;
}
.inv-renting {
  margin-top: 4px;
  padding: 6px 10px;
  background: #fdecea;
  border: 1px solid #f5c2bd;
  color: #c0260b;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}
.inv-rents {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #dde3ec;
}
.inv-rents-title {
  font-size: 12px;
  font-weight: 600;
  color: #4b5563;
  margin-bottom: 4px;
}
.inv-rent-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  padding: 2px 0;
}
.inv-rent-problem {
  color: #c0260b;
  background: #fdecea;
  padding: 0 6px;
  border-radius: 3px;
}
.inv-rent-waybill {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  color: #2f5fae;
  background: #eef3fb;
  border: 1px solid #d5e2f5;
  padding: 1px 8px;
  border-radius: 10px;
  cursor: pointer;
  user-select: none;
}
.inv-rent-waybill:hover {
  background: #dce9fb;
  border-color: #4d8dff;
}
</style>
