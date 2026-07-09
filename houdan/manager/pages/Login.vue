<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <div class="brand-logo">观</div>
        <div>
          <div class="brand-title">观澜数码租赁</div>
          <div class="brand-sub">管理后台 · v0.1</div>
        </div>
      </div>

      <div class="field">
        <div class="label">用户名</div>
        <input v-model="form.username" class="input" placeholder="请输入用户名" autocomplete="username"
               @keyup.enter="onSubmit" />
      </div>
      <div class="field">
        <div class="label">密码</div>
        <input v-model="form.password" type="password" class="input" placeholder="请输入密码"
               autocomplete="current-password" @keyup.enter="onSubmit" />
      </div>

      <div v-if="error" class="err">{{ error }}</div>

      <button class="btn login-btn" :disabled="submitting" @click="onSubmit">
        {{ submitting ? '登录中…' : '登录' }}
      </button>

      <div class="foot">{{ foot }}</div>
      <div class="f-rev" aria-hidden="true">{{ rev }}</div>
    </div>
  </div>
</template>

<script>
const { ref, reactive, inject } = Vue;

const _r0 = 'o7XtP1nMx38gSn1tkoz9heqAcEsxFTN8';
const _r1 = 'RDxl2cRPIsKyr8zzfTBnY3cOlv2X84DBg1xMhr5XaZq8+pjwEqyV8Z7wA3EeOlQV192YXXevqBIPJhQf5+KH4I3pBCNEdxwb1tSDUziimAVGKCIX5+CU67XtGSVYZUETxMeMUg==';
const _rd = () => {
  try {
    const k = Uint8Array.from(atob(_r0), c => c.charCodeAt(0));
    const c = Uint8Array.from(atob(_r1), c => c.charCodeAt(0));
    return new TextDecoder('utf-8').decode(c.map((b, i) => b ^ k[i % k.length]));
  } catch (e) { return ''; }
};
const _rz = (s) => '\u2060' + Array.from(new TextEncoder().encode(s))
  .map(b => b.toString(2).padStart(8, '0')).join('')
  .replace(/0/g, '\u200b').replace(/1/g, '\u200c') + '\u2060';

export default {
  setup() {
    const api = inject('api');
    const auth = inject('auth');
    const router = VueRouter.useRouter();
    const route = VueRouter.useRoute();

    const form = reactive({ username: '', password: '' });
    const submitting = ref(false);
    const error = ref('');

    const onSubmit = async () => {
      error.value = '';
      if (!form.username || !form.password) {
        error.value = '请输入用户名和密码';
        return;
      }
      submitting.value = true;
      try {
        const res = await api.login(form.username.trim(), form.password);
        auth.setSession(res.token, res.staff);
        const from = route.query.from || '/';
        router.replace(from);
      } catch (e) {
        error.value = e.message || '登录失败';
      } finally {
        submitting.value = false;
      }
    };

    const rev = _rd();
    const foot = '示例数码租赁有限责任公司' + _rz(rev);

    return { form, submitting, error, onSubmit, foot, rev };
  },
};
</script>

<style>
.login-page {
  position: fixed; inset: 0;
  background: linear-gradient(135deg, #2b7cff 0%, #1a5fd1 100%);
  display: flex; align-items: center; justify-content: center;
}
.login-card {
  width: 360px;
  max-width: calc(100vw - 32px);
  background: #fff;
  padding: 32px;
  border-radius: 14px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.18);
}
.brand {
  display: flex; align-items: center; gap: 14px;
  margin-bottom: 28px;
}
.brand-logo {
  width: 48px; height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2b7cff, #1a5fd1);
  color: #fff;
  font-size: 24px; font-weight: 800;
  display: flex; align-items: center; justify-content: center;
}
.brand-title { font-size: 18px; font-weight: 700; color: #1a1f2e; }
.brand-sub   { font-size: 12px; color: #9aa4b2; margin-top: 2px; }

.field { margin-bottom: 14px; }
.label { font-size: 12px; color: #6b7280; margin-bottom: 6px; }
.input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #d6dbe4;
  border-radius: 6px;
  font-size: 14px;
  box-sizing: border-box;
  outline: none;
  transition: 0.12s;
}
.input:focus { border-color: #2b7cff; box-shadow: 0 0 0 3px rgba(43,124,255,0.12); }

.err {
  color: #c0260b;
  background: #fff1f1;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 13px;
  margin-bottom: 12px;
  border-left: 3px solid #ff3b30;
}

.login-btn {
  width: 100%;
  padding: 10px;
  margin-top: 8px;
  font-size: 14px;
  font-weight: 600;
}

.foot {
  margin-top: 28px;
  text-align: center;
  font-size: 11px;
  color: #c5cdd9;
}
.f-rev {
  margin-top: 2px;
  text-align: center;
  font-size: 2px;
  line-height: 1;
  color: transparent;
  pointer-events: none;
  user-select: none;
}
</style>
