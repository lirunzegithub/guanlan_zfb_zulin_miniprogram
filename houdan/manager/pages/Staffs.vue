<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">工作人员</div>
      <button v-if="isAdmin" class="btn" @click="openNew">＋ 新增工作人员</button>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th style="width:60px">ID</th>
          <th style="width:140px">用户名</th>
          <th style="width:140px">姓名</th>
          <th style="width:100px">角色</th>
          <th style="width:160px">最近登录</th>
          <th style="width:240px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in list" :key="s.id">
          <td>{{ s.id }}</td>
          <td><strong>{{ s.username }}</strong></td>
          <td>{{ s.real_name || '-' }}</td>
          <td>
            <span :class="['tag', s.role === 'admin' ? 'tag-orange' : '']">{{ s.role }}</span>
            <span v-if="s.id === me.id" class="tag tag-green" style="margin-left:4px">本人</span>
          </td>
          <td><span class="muted">{{ fmtTime(s.last_login_at) }}</span></td>
          <td>
            <button v-if="canEdit(s)" class="btn-link" @click="openEdit(s)">编辑</button>
            <button class="btn-link" @click="openPwd(s)">改密</button>
            <button v-if="isAdmin && s.id !== me.id" class="btn-link danger" @click="onDelete(s)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="6" class="empty">暂无数据</td></tr>
        <tr v-if="loading"><td colspan="6" class="loading">加载中…</td></tr>
      </tbody>
    </table>
  </div>

  <!-- 新增 / 编辑 -->
  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal">
      <div class="modal-h">{{ form.id ? '编辑工作人员' : '新增工作人员' }}</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">用户名 *</div>
          <input class="input" v-model="form.username" :disabled="!!form.id" />
        </div>
        <div class="field">
          <div class="label">真实姓名</div>
          <input class="input" v-model="form.real_name" />
        </div>
        <div class="field" v-if="!form.id">
          <div class="label">初始密码 *（至少 6 位）</div>
          <input class="input" type="password" v-model="form.password" />
        </div>
        <div class="field" v-if="isAdmin">
          <div class="label">角色</div>
          <select class="select" v-model="form.role">
            <option value="operator">operator（普通运营）</option>
            <option value="admin">admin（超管，可管账号）</option>
          </select>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="modal = null">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>

  <!-- 改密 -->
  <div v-if="pwdModal" class="modal-mask" @click.self="pwdModal = null">
    <div class="modal" style="width:420px">
      <div class="modal-h">修改 {{ pwdModal.username }} 的密码</div>
      <div class="modal-body">
        <div v-if="pwdSelf" class="field">
          <div class="label">原密码</div>
          <input class="input" type="password" v-model="pwdForm.old_password" />
        </div>
        <div v-else class="muted" style="margin-bottom:14px">
          以 admin 身份代改，无需原密码。
        </div>
        <div class="field">
          <div class="label">新密码（至少 6 位）</div>
          <input class="input" type="password" v-model="pwdForm.new_password" />
        </div>
        <div class="field">
          <div class="label">再次输入新密码</div>
          <input class="input" type="password" v-model="pwdForm.new_password2" />
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="pwdModal = null">取消</button>
        <button class="btn" :disabled="pwdSaving" @click="savePwd">{{ pwdSaving ? '保存中…' : '保存' }}</button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, computed, inject, onMounted } = Vue;
export default {
  setup() {
    const api = inject('api');
    const auth = inject('auth');

    const list = ref([]);
    const loading = ref(true);
    const modal = ref(null);
    const form = ref({});
    const saving = ref(false);
    const pwdModal = ref(null);
    const pwdForm = ref({});
    const pwdSaving = ref(false);

    const me = computed(() => auth.state.staff || {});
    const isAdmin = computed(() => me.value.role === 'admin');
    const pwdSelf = computed(() => pwdModal.value && pwdModal.value.id === me.value.id);

    const fmtTime = (ts) => {
      if (!ts) return '从未';
      const d = new Date(ts * 1000);
      const z = (n) => (n < 10 ? '0' + n : '' + n);
      return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}`;
    };

    const canEdit = (s) => isAdmin.value || s.id === me.value.id;

    const fetch = async () => {
      loading.value = true;
      try { const r = await api.list('staffs'); list.value = r.list; }
      finally { loading.value = false; }
    };

    const openNew = () => {
      form.value = { username: '', real_name: '', password: '', role: 'operator' };
      modal.value = true;
    };
    const openEdit = (s) => {
      form.value = { ...s };
      modal.value = true;
    };

    const save = async () => {
      const f = form.value;
      if (!f.username?.trim()) { alert('用户名必填'); return; }
      if (!f.id && (!f.password || f.password.length < 6)) { alert('密码至少 6 位'); return; }
      saving.value = true;
      try {
        if (f.id) {
          await api.update('staffs', f.id, { real_name: f.real_name, role: f.role });
        } else {
          await api.create('staffs', { username: f.username, real_name: f.real_name, password: f.password, role: f.role });
        }
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    const onDelete = async (s) => {
      if (!confirm(`确认删除「${s.username}」？\n该账号将被物理删除，所有登录会话注销，无法恢复`)) return;
      try { await api.remove('staffs', s.id); await fetch(); }
      catch (e) { alert(e.message); }
    };

    const openPwd = (s) => {
      pwdModal.value = s;
      pwdForm.value = { old_password: '', new_password: '', new_password2: '' };
    };
    const savePwd = async () => {
      const f = pwdForm.value;
      if (!f.new_password || f.new_password.length < 6) { alert('新密码至少 6 位'); return; }
      if (f.new_password !== f.new_password2) { alert('两次密码不一致'); return; }
      pwdSaving.value = true;
      try {
        await api.changePassword(pwdModal.value.id, f.old_password, f.new_password);
        pwdModal.value = null;
        alert('密码已更新，所有该账号的登录会话已注销');
        if (pwdSelf.value) {
          // 自己改密 → 跳登录
          auth.clear();
          location.hash = '/login';
        }
      } catch (e) { alert(e.message); }
      finally { pwdSaving.value = false; }
    };

    onMounted(fetch);
    return {
      list, loading, me, isAdmin,
      modal, form, saving, openNew, openEdit, save, onDelete, canEdit,
      pwdModal, pwdForm, pwdSaving, pwdSelf, openPwd, savePwd,
      fmtTime,
    };
  },
};
</script>
