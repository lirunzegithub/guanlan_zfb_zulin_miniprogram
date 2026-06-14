<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">用户管理</div>
      <span class="muted">当前仅展示一条演示用户；后续接入真实用户系统</span>
    </div>
    <table class="table">
      <thead>
        <tr>
          <th style="width:120px">ID</th>
          <th style="width:120px">真实姓名</th>
          <th style="width:160px">手机号</th>
          <th style="width:160px">身份证</th>
          <th style="width:100px">实名</th>
          <th style="width:180px">注册时间</th>
          <th style="width:110px">共下单数量</th>
          <th style="width:180px">最近下单日期</th>
          <th style="width:130px">进行中订单</th>
          <th style="width:120px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in list" :key="u.id">
          <td>{{ u.id }}</td>
          <td>{{ u.real_name || '-' }}</td>
          <td>{{ u.phone || '-' }}</td>
          <td>{{ u.id_card || '-' }}</td>
          <td>
            <span v-if="u.verified" class="tag tag-green">已实名</span>
            <span v-else class="tag tag-gray">未实名</span>
          </td>
          <td>{{ u.created_at_text || '-' }}</td>
          <td>{{ u.order_count || 0 }}</td>
          <td>{{ u.last_order_at_text || '-' }}</td>
          <td>
            <span v-if="u.has_active_order" class="tag tag-green">有</span>
            <span v-else class="tag tag-gray">无</span>
          </td>
          <td><button class="btn-link" @click="openEdit(u)">编辑</button></td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="10" class="empty">暂无数据</td></tr>
        <tr v-if="loading"><td colspan="10" class="loading">加载中...</td></tr>
      </tbody>
    </table>
  </div>

  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal">
      <div class="modal-h">编辑用户</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">昵称</div>
          <input class="input" v-model="form.nickname" />
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">真实姓名</div>
            <input class="input" v-model="form.real_name" />
          </div>
          <div class="field" style="flex:1">
            <div class="label">手机号</div>
            <input class="input" v-model="form.phone" />
          </div>
        </div>
        <div class="field">
          <div class="label">身份证</div>
          <input class="input" v-model="form.id_card" />
        </div>
        <div class="field">
          <label><input type="checkbox" v-model="form.verified" /> 已实名</label>
        </div>

        <div class="field">
          <div class="label">收货地址</div>
          <div v-if="addrLoading" class="muted">加载中…</div>
          <div v-else-if="!addresses.length" class="muted">该用户暂无收货地址</div>
          <div v-else class="addr-list">
            <div v-for="a in addresses" :key="a.id" class="addr-item">
              <div class="addr-line1">
                <span class="addr-name">{{ a.receiver_name || '-' }}</span>
                <span class="addr-phone">{{ a.receiver_phone || '-' }}</span>
                <span v-if="a.is_default" class="tag tag-green">默认</span>
              </div>
              <div class="addr-full">{{ a.full || '-' }}</div>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="modal = null">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, inject, onMounted } = Vue;
export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const loading = ref(true);
    const modal = ref(null);
    const form = ref({});
    const saving = ref(false);
    const addresses = ref([]);
    const addrLoading = ref(false);

    const fetch = async () => {
      loading.value = true;
      try { const r = await api.list('users'); list.value = r.list; }
      finally { loading.value = false; }
    };

    const openEdit = async (u) => {
      form.value = { ...u };
      modal.value = true;
      // 懒加载该用户的收货地址
      addresses.value = [];
      addrLoading.value = true;
      try {
        const r = await api.userAddresses(u.id);
        addresses.value = (r && r.list) || [];
      } catch (e) {
        addresses.value = [];
      } finally {
        addrLoading.value = false;
      }
    };

    const save = async () => {
      saving.value = true;
      try {
        await api.update('users', form.value.id, form.value);
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    onMounted(fetch);
    return { list, loading, modal, form, saving, openEdit, save, addresses, addrLoading };
  }
};
</script>

<style scoped>
.addr-list { display: flex; flex-direction: column; gap: 8px; }
.addr-item {
  border: 1px solid var(--line, #e5e8ee);
  border-radius: 8px;
  padding: 8px 10px;
  background: #fafbfd;
}
.addr-line1 { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.addr-name { font-weight: 600; color: var(--text, #1a1f2e); }
.addr-phone { color: #4a5060; }
.addr-full { font-size: 12px; color: #6b7280; margin-top: 4px; line-height: 1.5; word-break: break-all; }
</style>
