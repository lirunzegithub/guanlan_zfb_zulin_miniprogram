<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">
        退款审核
        <span class="muted small" style="margin-left:10px">
          用户对扣款发起的退款申请，2 个工作日内处理
        </span>
      </div>
      <div class="row" style="gap:8px">
        <div class="tabs">
          <button
            v-for="t in tabs"
            :key="t.value"
            :class="['tab', tab === t.value ? 'active' : '']"
            @click="switchTab(t.value)">
            {{ t.label }}
            <span v-if="t.value !== 'all' && (counts[t.value] || 0) > 0"
                  class="tab-badge">{{ counts[t.value] }}</span>
          </button>
        </div>
        <button class="btn btn-ghost" @click="fetch">刷新</button>
      </div>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:180px">扣款单号 / 时间</th>
          <th style="width:160px">订单 / 商品</th>
          <th style="width:140px">用户</th>
          <th style="width:200px">扣款详情</th>
          <th style="width:90px">金额</th>
          <th>退款理由</th>
          <th style="width:140px">状态</th>
          <th style="width:170px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in list" :key="r.out_trade_no">
          <td>
            <div class="mono small">{{ r.out_trade_no }}</div>
            <div class="muted small">申请：{{ r.applied_at_text || '-' }}</div>
            <div v-if="r.reviewed_at_text" class="muted small">
              审核：{{ r.reviewed_at_text }}
              <span v-if="r.reviewer"> · {{ r.reviewer }}</span>
            </div>
          </td>
          <td>
            <div class="mono small">{{ r.order_id }}</div>
            <div>{{ r.product_name || '—' }}</div>
            <div class="muted small">订单状态：{{ r.order_status_label || r.order_status || '-' }}</div>
          </td>
          <td>
            <div>{{ r.user_nickname || ('#' + r.user_id) }}</div>
            <div class="muted small">{{ r.user_phone || '—' }}</div>
          </td>
          <td>
            <div>
              <span class="tag tag-orange" style="margin-right:6px">
                {{ r.reason_type_label || '扣款' }}
              </span>
            </div>
            <div v-if="r.reason_detail" class="muted small" style="margin-top:4px">
              {{ r.reason_detail }}
            </div>
          </td>
          <td>
            <div><strong>¥{{ fmt(r.amount) }}</strong></div>
            <div v-if="r.refunded_amount > 0" class="muted small">
              已退 ¥{{ fmt(r.refunded_amount) }}
            </div>
            <div v-if="r.refundable_amount > 0 && r.refundable_amount !== r.amount" class="small">
              剩可退 <strong>¥{{ fmt(r.refundable_amount) }}</strong>
            </div>
          </td>
          <td>
            <div class="reason-text">{{ r.reason || '—' }}</div>
            <div v-if="r.status === 'REJECTED' && r.rejected_reason" class="muted small" style="margin-top:6px">
              驳回理由：{{ r.rejected_reason }}
            </div>
          </td>
          <td>
            <span :class="['tag', statusCls(r.status)]">{{ r.status_label || r.status }}</span>
            <div v-if="r.refund_out_request_no" class="muted small mono" style="margin-top:4px">
              {{ r.refund_out_request_no }}
            </div>
          </td>
          <td>
            <template v-if="r.status === 'PENDING'">
              <button class="btn btn-sm" :disabled="busy[r.out_trade_no]"
                      @click="approve(r)">通过</button>
              <button class="btn btn-sm btn-danger" :disabled="busy[r.out_trade_no]"
                      style="margin-left:6px" @click="reject(r)">驳回</button>
            </template>
            <button v-else class="btn-link" @click="gotoOrder(r)">查看订单</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length">
          <td colspan="8" class="empty">{{ emptyText }}</td>
        </tr>
        <tr v-if="loading">
          <td colspan="8" class="loading">加载中…</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- 通过审核：自定义退款金额（默认全额） -->
  <div v-if="approveModal" class="modal-mask" @click.self="approveModal = null">
    <div class="modal" style="width: 480px; max-width: 95vw">
      <div class="modal-h">审核通过 · 发起退款</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">本次退款金额（元）</div>
          <input class="input" v-model.number="approveForm.amount" type="number"
                 step="0.01" :max="approveForm.refundable" />
          <div class="muted small">
            剩余可退：¥{{ fmt(approveForm.refundable) }}
            （默认全额退；如需部分退请改小）
          </div>
        </div>
        <div class="field">
          <div class="label">用户提交的退款理由</div>
          <div class="muted small reason-quote">{{ approveForm.reason }}</div>
        </div>
        <div class="muted small" style="line-height:1.6">
          通过后将立即调用支付宝退款接口（alipay.trade.refund），原路退回用户账户。
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="approveModal = null">取消</button>
        <button class="btn" :disabled="!canApprove || submitting"
                @click="doApprove">{{ submitting ? '提交中…' : '确认通过并退款' }}</button>
      </div>
    </div>
  </div>

  <!-- 驳回审核：填写驳回理由 -->
  <div v-if="rejectModal" class="modal-mask" @click.self="rejectModal = null">
    <div class="modal" style="width: 480px; max-width: 95vw">
      <div class="modal-h">驳回退款申请</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">用户提交的退款理由</div>
          <div class="muted small reason-quote">{{ rejectForm.reason }}</div>
        </div>
        <div class="field">
          <div class="label">驳回理由 *</div>
          <textarea class="input" v-model="rejectForm.rejectReason"
                    rows="4" maxlength="500"
                    placeholder="请说明驳回原因（如：扣款理由真实存在 / 已签收商品出现破损 / 已与用户沟通确认 …）"></textarea>
          <div class="muted small">
            {{ (rejectForm.rejectReason || '').length }}/500，至少 5 个字。理由会展示在用户订单详情。
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="rejectModal = null">取消</button>
        <button class="btn btn-danger" :disabled="!canReject || submitting"
                @click="doReject">{{ submitting ? '提交中…' : '确认驳回' }}</button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, reactive, computed, inject, onMounted } = Vue;

const STATUS_CLS = {
  PENDING:  'tag-orange',
  APPROVED: 'tag-green',
  REJECTED: 'tag-red',
};

export default {
  setup() {
    const api = inject('api');
    const router = VueRouter.useRouter();

    const tabs = [
      { value: 'pending',  label: '待审核' },
      { value: 'approved', label: '已通过' },
      { value: 'rejected', label: '已驳回' },
      { value: 'all',      label: '全部'   },
    ];
    const tab = ref('pending');
    const list = ref([]);
    const counts = ref({ pending: 0, approved: 0, rejected: 0 });
    const loading = ref(true);
    const busy = reactive({});

    const emptyText = computed(() => ({
      pending:  '暂无待审核的退款申请',
      approved: '暂无已通过记录',
      rejected: '暂无已驳回记录',
      all:      '暂无退款申请',
    }[tab.value] || '暂无数据'));

    const fmt = (v) => (Number(v) || 0).toFixed(2);
    const statusCls = (s) => STATUS_CLS[s] || 'tag-gray';

    const fetch = async () => {
      loading.value = true;
      try {
        const r = await api.listRefundApplies(tab.value);
        list.value = r.list || [];
        counts.value = r.counts || { pending: 0, approved: 0, rejected: 0 };
      } catch (e) {
        alert(e.message || '加载失败');
      } finally {
        loading.value = false;
      }
    };

    const switchTab = (v) => {
      if (tab.value === v) return;
      tab.value = v;
      fetch();
    };

    // ---------- 通过 ----------
    const approveModal = ref(null);
    const approveForm = reactive({
      out_trade_no: '', amount: 0, refundable: 0, reason: '',
    });
    const canApprove = computed(() =>
      Number(approveForm.amount) > 0 &&
      Number(approveForm.amount) <= Number(approveForm.refundable) + 1e-9
    );
    const submitting = ref(false);

    const approve = (r) => {
      approveForm.out_trade_no = r.out_trade_no;
      approveForm.refundable   = Number(r.refundable_amount) || 0;
      approveForm.amount       = Number(r.refundable_amount) || 0;
      approveForm.reason       = r.reason || '';
      approveModal.value = true;
    };
    const doApprove = async () => {
      if (!canApprove.value) return;
      const otn = approveForm.out_trade_no;
      submitting.value = true;
      busy[otn] = true;
      try {
        await api.approveRefundApply(otn, { amount: Number(approveForm.amount) });
        approveModal.value = null;
        await fetch();
        alert('已通过审核，退款已发起');
      } catch (e) {
        alert(e.message || '审核失败');
      } finally {
        submitting.value = false;
        delete busy[otn];
      }
    };

    // ---------- 驳回 ----------
    const rejectModal = ref(null);
    const rejectForm = reactive({
      out_trade_no: '', reason: '', rejectReason: '',
    });
    const canReject = computed(() =>
      (rejectForm.rejectReason || '').trim().length >= 5
    );
    const reject = (r) => {
      rejectForm.out_trade_no = r.out_trade_no;
      rejectForm.reason       = r.reason || '';
      rejectForm.rejectReason = '';
      rejectModal.value = true;
    };
    const doReject = async () => {
      if (!canReject.value) return;
      const otn = rejectForm.out_trade_no;
      submitting.value = true;
      busy[otn] = true;
      try {
        await api.rejectRefundApply(otn, (rejectForm.rejectReason || '').trim());
        rejectModal.value = null;
        await fetch();
      } catch (e) {
        alert(e.message || '驳回失败');
      } finally {
        submitting.value = false;
        delete busy[otn];
      }
    };

    const gotoOrder = (r) => {
      if (r.order_id) router.push({ path: '/orders', query: { id: r.order_id } });
    };

    onMounted(fetch);

    return {
      tabs, tab, list, counts, loading, busy, emptyText,
      fmt, statusCls,
      fetch, switchTab,
      approveModal, approveForm, canApprove, approve, doApprove,
      rejectModal,  rejectForm,  canReject,  reject,  doReject,
      submitting,
      gotoOrder,
    };
  },
};
</script>

<style scoped>
.tabs { display: inline-flex; gap: 0; }
.tab {
  position: relative;
  padding: 6px 14px;
  background: #f7f9fc;
  border: 1px solid #e7ecf2;
  color: #5b6376;
  cursor: pointer;
  font-size: 13px;
}
.tab:first-of-type { border-radius: 6px 0 0 6px; }
.tab:last-of-type  { border-radius: 0 6px 6px 0; border-left: none; }
.tab + .tab { border-left: none; }
.tab:hover { background: #eef2f7; }
.tab.active {
  background: #2b7cff;
  color: #fff;
  border-color: #2b7cff;
  z-index: 1;
}
.tab-badge {
  display: inline-block;
  margin-left: 6px;
  min-width: 18px;
  padding: 0 6px;
  height: 18px;
  line-height: 18px;
  border-radius: 9px;
  background: #f0560b;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  text-align: center;
  vertical-align: 1px;
}
.tab.active .tab-badge { background: #fff; color: #f0560b; }

.mono { font-family: 'SF Mono', Consolas, monospace; }
.small { font-size: 12px; line-height: 1.5; }
.empty, .loading {
  text-align: center;
  color: #9aa0ac;
  padding: 32px 0;
}
.reason-text {
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
  font-size: 13px;
  color: #1a1f2e;
}
.reason-quote {
  padding: 8px 10px;
  background: #f7f9fc;
  border: 1px solid #e7ecf2;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  color: #5b6376;
}
</style>
