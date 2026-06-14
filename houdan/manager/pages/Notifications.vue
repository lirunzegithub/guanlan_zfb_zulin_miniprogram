<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">
        支付宝回调日志
        <span class="muted" style="margin-left:8px">共 {{ list.length }} 条，最近一次 {{ lastAt }}</span>
      </div>
      <div class="row" style="gap:8px">
        <select class="select" v-model="filter" style="width:160px" @change="reload">
          <option value="">全部通道</option>
          <option v-for="c in channels" :key="c" :value="c">{{ c }}</option>
        </select>
        <label class="muted" style="display:inline-flex;align-items:center;gap:6px">
          <input type="checkbox" v-model="autoRefresh" /> 自动刷新 5s
        </label>
        <button class="btn btn-ghost" @click="reload">立即刷新</button>
        <button class="btn btn-danger" @click="onClear">清空</button>
      </div>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:160px">时间</th>
          <th style="width:130px">通道</th>
          <th style="width:80px">验签</th>
          <th style="width:80px">业务</th>
          <th style="width:70px">重复</th>
          <th>关键字段</th>
          <th style="width:80px">详情</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="it in list" :key="it.id">
          <tr :class="rowCls(it)" @click="toggle(it.id)">
            <td><span class="muted">{{ fmtTime(it.ts) }}</span></td>
            <td><span class="tag">{{ it.channel }}</span></td>
            <td>
              <span :class="['tag', it.verified ? 'tag-green' : 'tag-red']">
                {{ it.verified ? '通过' : '失败' }}
              </span>
            </td>
            <td>
              <span :class="['tag', it.business_ok ? 'tag-green' : 'tag-orange']">
                {{ it.business_ok ? '成功' : '失败' }}
              </span>
            </td>
            <td>
              <span v-if="it.duplicate" class="tag tag-gray">重复</span>
              <span v-else class="muted">-</span>
            </td>
            <td class="ellipsis">{{ shortFields(it.params) }}</td>
            <td><span class="btn-link">{{ open[it.id] ? '收起' : '展开' }}</span></td>
          </tr>
          <tr v-if="open[it.id]" class="detail-row">
            <td colspan="7">
              <div class="detail-body">
                <div v-if="it.note" class="note">备注：{{ it.note }}</div>
                <div class="kv-grid">
                  <div v-for="(v, k) in it.params" :key="k" class="kv">
                    <span class="kv-k">{{ k }}</span>
                    <span class="kv-v">{{ v }}</span>
                  </div>
                </div>
                <div v-if="it.raw_body" class="raw">
                  <div class="raw-h">原始 body</div>
                  <pre>{{ it.raw_body }}</pre>
                </div>
              </div>
            </td>
          </tr>
        </template>
        <tr v-if="!loading && !list.length">
          <td colspan="7" class="empty">
            还没有任何回调消息。<br>
            <span class="muted">支付宝异步通知一旦到达就会出现在这里（无论验签是否通过）。</span>
          </td>
        </tr>
        <tr v-if="loading"><td colspan="7" class="loading">加载中…</td></tr>
      </tbody>
    </table>
  </div>
</template>

<script>
const { ref, reactive, inject, onMounted, onUnmounted, computed } = Vue;

const KEY_FIELDS = [
  'out_order_no', 'out_trade_no', 'trade_no', 'auth_no',
  'operation_type', 'trade_status', 'status', 'amount',
  // merchant_order_sync 回调专属
  'out_biz_no', 'op_code',
];

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const open = reactive({});
    const filter = ref('');
    const autoRefresh = ref(true);
    const loading = ref(false);
    let timer = null;

    const channels = [
      'auth_freeze', 'auth_unfreeze', 'auth_pay',
      'trade', 'trade_refund', 'zhima',
      // 主动同步流水（成功 + 失败）和支付宝端反推的履约回调
      'merchant_order_sync', 'merchant_order_sync_notify',
    ];

    const lastAt = computed(() => {
      if (!list.value.length) return '—';
      return fmtTime(list.value[0].ts);
    });

    function fmtTime(ms) {
      if (!ms) return '';
      const d = new Date(ms);
      const z = (n) => (n < 10 ? '0' + n : '' + n);
      return `${d.getMonth() + 1}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`;
    }

    function shortFields(p) {
      if (!p) return '';
      const picked = KEY_FIELDS.map(k => (p[k] !== undefined ? `${k}=${p[k]}` : null)).filter(Boolean);
      return picked.join('  ');
    }

    function rowCls(it) {
      if (!it.verified) return 'row-bad';
      if (!it.business_ok) return 'row-warn';
      return '';
    }

    function toggle(id) { open[id] = !open[id]; }

    async function reload() {
      loading.value = true;
      try {
        const r = await api.notifyLogs({ channel: filter.value, limit: 200 });
        list.value = r.list || [];
      } finally { loading.value = false; }
    }

    async function onClear() {
      if (!confirm('清空所有回调记录？')) return;
      await api.clearLogs();
      list.value = [];
    }

    function tick() {
      if (timer) clearInterval(timer);
      if (autoRefresh.value) timer = setInterval(reload, 5000);
    }

    onMounted(() => { reload(); tick(); });
    onUnmounted(() => { if (timer) clearInterval(timer); });

    return {
      list, open, filter, autoRefresh, loading, channels, lastAt,
      fmtTime, shortFields, rowCls, toggle, reload, onClear,
    };
  },
};
</script>

<style>
.row-bad td  { background: #fff4f2 !important; }
.row-warn td { background: #fff8ee !important; }

.ellipsis {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: #4a5060;
}

.detail-row > td {
  background: #f7f9fc;
  padding: 14px 18px;
}
.detail-body { font-size: 12px; }
.detail-body .note {
  color: #c0260b;
  margin-bottom: 8px;
}
.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 18px;
}
.kv {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px dashed #eef1f6;
  font-family: ui-monospace, Menlo, monospace;
}
.kv-k {
  width: 140px;
  color: #6b7280;
  flex-shrink: 0;
}
@media (max-width: 768px) {
  .kv-grid { grid-template-columns: 1fr; }
  .kv-k { width: 110px; }
}
.kv-v {
  flex: 1;
  word-break: break-all;
  color: #1a1f2e;
}
.raw {
  margin-top: 12px;
  padding: 10px 12px;
  background: #1a1f2e;
  color: #d6dbe4;
  border-radius: 6px;
  font-size: 11px;
}
.raw-h {
  color: #9aa4b2;
  margin-bottom: 6px;
}
.raw pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: ui-monospace, Menlo, monospace;
}
</style>
