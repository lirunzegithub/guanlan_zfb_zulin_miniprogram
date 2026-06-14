<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">
        应用网关消息
        <span class="muted" style="margin-left:8px">
          共 {{ list.length }} 条
          <span v-if="lastAt"> · 最近 {{ lastAt }}</span>
        </span>
      </div>
      <div class="row" style="gap:8px">
        <select class="select" v-model="methodFilter" style="width:240px" @change="reload">
          <option value="">全部消息类型</option>
          <option v-for="m in methods" :key="m" :value="m">{{ m }}</option>
        </select>
        <label class="muted" style="display:inline-flex;align-items:center;gap:6px">
          <input type="checkbox" v-model="autoRefresh" @change="tick" /> 自动刷新 5s
        </label>
        <button class="btn btn-ghost" @click="reload">立即刷新</button>
      </div>
    </div>

    <div class="hint">
      此页面专门展示开放平台「应用网关」推过来的<b>平台级消息</b>：应用授权变更、模板消息订阅状态、平台公告等。
      不包含业务通知（押金冻结/解冻/支付等），那些请去
      <router-link to="/notifications">回调日志</router-link>。
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:160px">时间</th>
          <th style="width:280px">msg_method</th>
          <th style="width:80px">验签</th>
          <th>关键字段</th>
          <th style="width:80px">详情</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="it in list" :key="it.id">
          <tr :class="rowCls(it)" @click="toggle(it.id)">
            <td><span class="muted">{{ fmtTime(it.ts) }}</span></td>
            <td>
              <span class="tag tag-method">{{ msgMethodOf(it) }}</span>
            </td>
            <td>
              <span :class="['tag', it.verified ? 'tag-green' : 'tag-red']">
                {{ it.verified ? '通过' : (it.params && it.params.sign ? '失败' : '无签') }}
              </span>
            </td>
            <td class="ellipsis">{{ shortFields(it.params) }}</td>
            <td><span class="btn-link">{{ open[it.id] ? '收起' : '展开' }}</span></td>
          </tr>
          <tr v-if="open[it.id]" class="detail-row">
            <td colspan="5">
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
          <td colspan="5" class="empty">
            还没有任何网关消息。<br>
            <span class="muted">
              配置 <code>https://your-domain.example.com/api/alipay/notify/gateway</code> 后，
              支付宝推送的应用授权变更、模板订阅状态等消息会出现在这里。
            </span>
          </td>
        </tr>
        <tr v-if="loading"><td colspan="5" class="loading">加载中…</td></tr>
      </tbody>
    </table>
  </div>
</template>

<script>
const { ref, reactive, inject, computed, onMounted, onUnmounted } = Vue;

// 网关消息的 channel 在后端记录为 "gateway:{msg_method}"，前端剥掉前缀展示
const PREFIX = 'gateway:';

// 网关消息没有标准的"业务关键字段"，挑几个常出现的展示
const KEY_FIELDS = [
  'msg_method', 'app_id', 'biz_type', 'auth_app_id', 'user_id',
  'scope', 'status', 'notify_id', 'notify_type',
];

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const open = reactive({});
    const methodFilter = ref('');
    const autoRefresh = ref(true);
    const loading = ref(false);
    let timer = null;

    // 把已见过的 msg_method 自动收集到下拉框，第一次见就追加
    const methods = ref([]);

    const lastAt = computed(() => list.value.length ? fmtTime(list.value[0].ts) : '');

    function fmtTime(ms) {
      if (!ms) return '';
      const d = new Date(ms);
      const z = (n) => (n < 10 ? '0' + n : '' + n);
      return `${d.getMonth() + 1}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`;
    }

    function msgMethodOf(it) {
      const ch = String(it.channel || '');
      if (ch.startsWith(PREFIX)) return ch.slice(PREFIX.length);
      return (it.params && it.params.msg_method) || ch || '-';
    }

    function shortFields(p) {
      if (!p) return '';
      const picked = KEY_FIELDS
        .map(k => (p[k] !== undefined ? `${k}=${p[k]}` : null))
        .filter(Boolean);
      return picked.join('  ');
    }

    function rowCls(it) {
      if (it.params && it.params.sign && !it.verified) return 'row-bad';
      return '';
    }

    function toggle(id) { open[id] = !open[id]; }

    async function reload() {
      loading.value = true;
      try {
        // methodFilter 非空 → 精确 channel；否则 prefix=gateway: 拿全部网关消息
        const params = methodFilter.value
          ? { channel: PREFIX + methodFilter.value, limit: 200 }
          : { prefix: PREFIX, limit: 200 };
        const r = await api.notifyLogs(params);
        list.value = r.list || [];

        // 增量收集下拉框选项
        const seen = new Set(methods.value);
        for (const it of list.value) {
          const m = msgMethodOf(it);
          if (m && m !== '-' && !seen.has(m)) {
            seen.add(m);
            methods.value.push(m);
          }
        }
      } finally { loading.value = false; }
    }

    function tick() {
      if (timer) { clearInterval(timer); timer = null; }
      if (autoRefresh.value) timer = setInterval(reload, 5000);
    }

    onMounted(() => { reload(); tick(); });
    onUnmounted(() => { if (timer) clearInterval(timer); });

    return {
      list, open, methodFilter, autoRefresh, loading, methods, lastAt,
      fmtTime, msgMethodOf, shortFields, rowCls, toggle, reload, tick,
    };
  },
};
</script>

<style>
.hint {
  margin: 12px 18px 0;
  padding: 10px 14px;
  background: #f3f7ff;
  border-left: 3px solid #4d8dff;
  border-radius: 4px;
  color: #3d5680;
  font-size: 13px;
  line-height: 1.6;
}
.hint code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  background: #fff;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid #d9e3f6;
}
.tag-method {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  color: #1a1f2e;
}

.row-bad td { background: #fff4f2 !important; }

.ellipsis {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  color: #4a5060;
}

.detail-row > td { background: #f7f9fc; padding: 14px 18px; }
.detail-body { font-size: 12px; }
.detail-body .note { color: #c0260b; margin-bottom: 8px; }
.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px 18px;
}
.kv {
  display: flex; gap: 8px; padding: 4px 0;
  border-bottom: 1px dashed #eef1f6;
  font-family: ui-monospace, Menlo, monospace;
}
.kv-k { width: 140px; color: #6b7280; flex-shrink: 0; }
.kv-v { flex: 1; word-break: break-all; color: #1a1f2e; }
@media (max-width: 768px) {
  .kv-grid { grid-template-columns: 1fr; }
  .kv-k { width: 110px; }
}
.raw {
  margin-top: 12px; padding: 10px 12px;
  background: #1a1f2e; color: #d6dbe4; border-radius: 6px; font-size: 11px;
}
.raw-h { color: #9aa4b2; margin-bottom: 6px; }
.raw pre {
  margin: 0; white-space: pre-wrap; word-break: break-all;
  font-family: ui-monospace, Menlo, monospace;
}
</style>
</content>
</invoke>