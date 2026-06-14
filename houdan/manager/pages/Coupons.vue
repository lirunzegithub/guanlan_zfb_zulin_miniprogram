<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">优惠券（满减）</div>
      <button class="btn" @click="openNew">＋ 新增满减券</button>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:60px">ID</th>
          <th>名称</th>
          <th style="width:160px">满减规则</th>
          <th style="width:120px">状态</th>
          <th style="width:200px">有效期</th>
          <th style="width:130px">领取 / 库存</th>
          <th style="width:220px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in list" :key="c.id">
          <td>{{ c.id }}</td>
          <td>
            <div style="font-weight:600">{{ c.name }}</div>
            <div class="muted" v-if="c.remark">{{ c.remark }}</div>
          </td>
          <td>
            <span class="rule-pill">满 ¥{{ fmt(c.threshold) }} 减 ¥{{ fmt(c.discount) }}</span>
          </td>
          <td>
            <span :class="['tag', statusCls(c)]">{{ statusText(c) }}</span>
          </td>
          <td>
            <div class="muted">{{ fmtRange(c.start_at, c.end_at) }}</div>
          </td>
          <td>
            <span>{{ c.claimed_quantity || 0 }}</span>
            <span class="muted"> / {{ c.total_quantity > 0 ? c.total_quantity : '不限' }}</span>
          </td>
          <td>
            <button class="btn-link" @click="openEdit(c)">编辑</button>
            <button class="btn-link" @click="toggleStatus(c)">{{ c.status === 'on' ? '下架' : '上架' }}</button>
            <button class="btn-link" @click="viewGrants(c)">领取明细</button>
            <button class="btn-link danger" @click="remove(c)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="7" class="empty">暂无优惠券，点右上「＋ 新增满减券」开始配置</td></tr>
        <tr v-if="loading"><td colspan="7" class="loading">加载中...</td></tr>
      </tbody>
    </table>
  </div>

  <!-- 编辑弹窗 -->
  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal">
      <div class="modal-h">{{ form.id ? '编辑满减券' : '新增满减券' }}</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">名称 <span class="req">*</span></div>
          <input class="input" v-model="form.name" placeholder="例如：新用户首单 100-20" maxlength="40" />
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">门槛金额（元） <span class="req">*</span></div>
            <input type="number" min="0" step="0.01" class="input" v-model.number="form.threshold" placeholder="满多少" />
          </div>
          <div class="field" style="flex:1">
            <div class="label">减免金额（元） <span class="req">*</span></div>
            <input type="number" min="0" step="0.01" class="input" v-model.number="form.discount" placeholder="减多少" />
          </div>
        </div>
        <div class="preview-line">
          <span class="rule-pill" v-if="rulePreview">{{ rulePreview }}</span>
          <span v-else class="muted">填写门槛与减免金额后会显示规则预览</span>
        </div>

        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">开始时间</div>
            <input type="datetime-local" class="input" v-model="form._startLocal" />
            <div class="muted">留空表示不限制开始</div>
          </div>
          <div class="field" style="flex:1">
            <div class="label">结束时间</div>
            <input type="datetime-local" class="input" v-model="form._endLocal" />
            <div class="muted">留空表示长期有效</div>
          </div>
        </div>

        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">总库存（0 表示不限）</div>
            <input type="number" min="0" class="input" v-model.number="form.total_quantity" />
          </div>
          <div class="field" style="flex:1">
            <div class="label">每人限领（0 表示不限）</div>
            <input type="number" min="0" class="input" v-model.number="form.per_user_limit" />
          </div>
          <div class="field" style="width:160px">
            <div class="label">状态</div>
            <select class="select" v-model="form.status">
              <option value="on">上架</option>
              <option value="off">下架</option>
            </select>
          </div>
        </div>

        <div class="field">
          <div class="label">备注（仅后台可见）</div>
          <textarea class="textarea" v-model="form.remark" maxlength="200" placeholder="例如：双11 限时活动"></textarea>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="modal = null">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>

  <!-- 领取明细弹窗 -->
  <div v-if="grantModal" class="modal-mask" @click.self="grantModal = null">
    <div class="modal" style="max-width:720px">
      <div class="modal-h">「{{ grantModal.coupon.name }}」领取明细</div>
      <div class="modal-body">
        <table class="table">
          <thead>
            <tr>
              <th style="width:80px">ID</th>
              <th>用户 ID</th>
              <th style="width:100px">状态</th>
              <th style="width:170px">领取时间</th>
              <th>使用订单</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="g in grantModal.list" :key="g.id">
              <td>{{ g.id }}</td>
              <td>{{ g.user_id }}</td>
              <td><span :class="['tag', grantCls(g.status)]">{{ grantText(g.status) }}</span></td>
              <td>{{ fmtTs(g.claimed_at) }}</td>
              <td>{{ g.order_id || '-' }}</td>
            </tr>
            <tr v-if="!grantModal.list.length"><td colspan="5" class="empty">暂无领取记录</td></tr>
          </tbody>
        </table>
      </div>
      <div class="modal-f">
        <button class="btn" @click="grantModal = null">关闭</button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, computed, inject, onMounted } = Vue;

// datetime-local <-> unix 秒
function toLocalInput(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fromLocalInput(v) {
  if (!v) return 0;
  const ts = new Date(v).getTime();
  return ts ? Math.floor(ts / 1000) : 0;
}
function fmtTsStr(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n) => (n < 10 ? '0' + n : '' + n);
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const loading = ref(true);
    const modal = ref(null);
    const form = ref({});
    const saving = ref(false);
    const grantModal = ref(null);

    const fmt = (v) => {
      const n = Number(v) || 0;
      return n.toFixed(2).replace(/\.00$/, '');
    };

    const rulePreview = computed(() => {
      const t = Number(form.value.threshold);
      const d = Number(form.value.discount);
      if (!t || !d) return '';
      return `满 ¥${fmt(t)} 减 ¥${fmt(d)}`;
    });

    const statusCls = (c) => {
      if (c.status !== 'on') return 'tag-gray';
      const now = Math.floor(Date.now() / 1000);
      if (c.end_at && now > c.end_at) return 'tag-gray';
      if (c.start_at && now < c.start_at) return 'tag-orange';
      if (c.total_quantity > 0 && (c.claimed_quantity || 0) >= c.total_quantity) return 'tag-red';
      return 'tag-green';
    };
    const statusText = (c) => {
      if (c.status !== 'on') return '已下架';
      const now = Math.floor(Date.now() / 1000);
      if (c.end_at && now > c.end_at) return '已过期';
      if (c.start_at && now < c.start_at) return '未开始';
      if (c.total_quantity > 0 && (c.claimed_quantity || 0) >= c.total_quantity) return '已抢光';
      return '生效中';
    };

    const fmtRange = (s, e) => {
      if (!s && !e) return '长期有效';
      if (s && e) return `${fmtTsStr(s)} 至 ${fmtTsStr(e)}`;
      if (s) return `${fmtTsStr(s)} 起`;
      return `至 ${fmtTsStr(e)}`;
    };

    const fetch = async () => {
      loading.value = true;
      try { const r = await api.list('coupons'); list.value = r.list || []; }
      finally { loading.value = false; }
    };

    const openNew = () => {
      form.value = {
        name: '', threshold: '', discount: '',
        status: 'on',
        start_at: 0, end_at: 0,
        _startLocal: '', _endLocal: '',
        total_quantity: 0, per_user_limit: 1,
        remark: '',
      };
      modal.value = true;
    };

    const openEdit = (c) => {
      form.value = {
        ...c,
        _startLocal: toLocalInput(c.start_at),
        _endLocal: toLocalInput(c.end_at),
      };
      modal.value = true;
    };

    const save = async () => {
      const body = { ...form.value };
      body.threshold = Number(body.threshold);
      body.discount = Number(body.discount);
      body.start_at = fromLocalInput(body._startLocal);
      body.end_at = fromLocalInput(body._endLocal);
      delete body._startLocal;
      delete body._endLocal;
      saving.value = true;
      try {
        if (body.id) await api.update('coupons', body.id, body);
        else await api.create('coupons', body);
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message || '保存失败'); }
      finally { saving.value = false; }
    };

    const toggleStatus = async (c) => {
      const next = c.status === 'on' ? 'off' : 'on';
      try { await api.update('coupons', c.id, { status: next }); await fetch(); }
      catch (e) { alert(e.message || '操作失败'); }
    };

    const remove = async (c) => {
      if (!confirm(`确认删除「${c.name}」？已领取的实例不会被删除，但模板移除后无法继续领取。`)) return;
      try { await api.remove('coupons', c.id); await fetch(); }
      catch (e) { alert(e.message || '删除失败'); }
    };

    const viewGrants = async (c) => {
      try {
        const r = await api.list(`coupons/${c.id}/grants`);
        grantModal.value = { coupon: c, list: r.list || [] };
      } catch (e) { alert(e.message || '加载失败'); }
    };

    const grantCls = (s) => s === 'used' ? 'tag-green' : s === 'expired' ? 'tag-gray' : 'tag-orange';
    const grantText = (s) => s === 'used' ? '已使用' : s === 'expired' ? '已过期' : '未使用';

    onMounted(fetch);
    return {
      list, loading, modal, form, saving, grantModal,
      fmt, rulePreview, statusCls, statusText, fmtRange,
      fmtTs: fmtTsStr, grantCls, grantText,
      openNew, openEdit, save, toggleStatus, remove, viewGrants,
    };
  },
};
</script>

<style scoped>
.toolbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }
.req { color: var(--danger); margin-left:2px; }
.rule-pill {
  display:inline-block;
  padding:4px 10px;
  border-radius:999px;
  background:linear-gradient(135deg,#ffefc4 0%,#ffb84d 100%);
  color:#7a4500;
  font-weight:600;
  font-size:12px;
}
.preview-line { margin:-4px 0 8px 0; min-height:24px; }
.empty, .loading { text-align:center; color:var(--text-3); padding:24px; }
</style>
