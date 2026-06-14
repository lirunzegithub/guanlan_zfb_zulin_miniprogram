<template>
  <div v-if="!isAdmin" class="card forbid">
    <div class="forbid-ico">⛔</div>
    <div class="forbid-title">无权访问</div>
    <div class="forbid-sub">
      系统设置页面仅限 <b>admin</b> 角色查看与修改。<br>
      当前账号角色：<code>{{ auth.state.staff?.role || '未知' }}</code>
    </div>
  </div>

  <div v-else class="card">
    <div class="toolbar">
      <div class="card-title">系统设置</div>
      <div class="row" style="gap:8px">
        <button class="btn btn-ghost" @click="reload" :disabled="loading">重新加载</button>
        <button class="btn" :disabled="loading || !dirty" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </div>

    <div v-if="loading" class="loading" style="padding:40px">加载中…</div>
    <div v-else class="form-grid">

      <div class="form-field">
        <label class="form-label">软件 LOGO</label>
        <div class="logo-edit">
          <div class="logo-preview">
            <img v-if="form.logo_url" :src="absUrl(form.logo_url)" alt="logo" />
            <span v-else class="logo-ph">无</span>
          </div>
          <div class="logo-ops">
            <label class="btn btn-sm">
              <input type="file" accept="image/*" hidden @change="onLogoPick" />
              {{ logoUploading ? '上传中…' : (form.logo_url ? '更换' : '上传') }}
            </label>
            <button v-if="form.logo_url" type="button" class="btn btn-ghost btn-sm" @click="form.logo_url = ''">移除</button>
          </div>
        </div>
        <div class="form-hint">
          后台浏览器标签页图标 + 左上角品牌、小程序「我的」头像都用它。建议正方形 PNG（≥ 200×200）。改后双端同步生效。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">物流免租期（天）</label>
        <input class="input" type="number" min="0" max="30" v-model.number="form.ship_free_days" />
        <div class="form-hint">
          起租日起前 N 天免收租金；偏远地区物流耗时长可适当上调。当前推荐 3 天。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">客服电话</label>
        <input class="input" type="text" v-model.trim="form.service_phone" placeholder="如 400-000-0000" />
        <div class="form-hint">
          展示在小程序客服中心 / 我的页底部；用户拨打的就是这个号。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">公司名称</label>
        <input class="input" type="text" v-model.trim="form.company_name" placeholder="如 示例数码租赁有限责任公司" />
        <div class="form-hint">
          展示在小程序「我的」底部与本后台侧栏底部；改后双端同步生效。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">押金冻结模式</label>
        <div class="seg-row">
          <label class="seg">
            <input type="radio" :value="true" v-model="form.freeze_includes_rent" />
            <span>押金 + 租金（合并冻结）</span>
          </label>
          <label class="seg">
            <input type="radio" :value="false" v-model="form.freeze_includes_rent" />
            <span>仅押金</span>
          </label>
        </div>
        <div class="form-hint">
          决定下单时调支付宝 freeze 的冻结金额组成：<br>
          ・<b>押金 + 租金</b>：合并冻结一次到位，归还核验时可走"扣后解冻剩余"扣实际租金<br>
          ・<b>仅押金</b>：只冻押金作担保，租金到期再单独扣<br>
          注：仅影响<b>新下单</b>；已下单订单按下单时快照（freeze_amount 字段）执行。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">租期日历手动选择</label>
        <div class="seg-row">
          <label class="seg">
            <input type="radio" :value="true" v-model="form.allow_manual_date_pick" />
            <span>允许手选</span>
          </label>
          <label class="seg">
            <input type="radio" :value="false" v-model="form.allow_manual_date_pick" />
            <span>仅快捷预设</span>
          </label>
        </div>
        <div class="form-hint">
          控制商品详情「选择租期」抽屉里，用户能否在日历上自行点选起止日期：<br>
          ・<b>允许手选</b>：顶部快捷天数 + 日历手动点选都可用（默认）<br>
          ・<b>仅快捷预设</b>：只能点顶部固定天数；日历仍展示选中区间但禁止点选
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">租金可为 0（租押分离）</label>
        <div class="seg-row">
          <label class="seg">
            <input type="radio" :value="false" v-model="form.allow_zero_rent" />
            <span>必须大于 0</span>
          </label>
          <label class="seg">
            <input type="radio" :value="true" v-model="form.allow_zero_rent" />
            <span>允许为 0</span>
          </label>
        </div>
        <div class="form-hint">
          控制商品「价格分段」里日租金能否填 0：<br>
          ・<b>必须大于 0</b>：硬性规则，防止漏配导致 0 元白嫖（默认）<br>
          ・<b>允许为 0</b>：租押分离场景 —— 租金线下/另行处理，商品仅冻押金担保时可配 0
        </div>
        <div class="form-hint" style="margin-top:8px;padding:8px 10px;background:#fff8e6;border-radius:6px">
          ⚠️ 与下方「零价兜底」联动：<b>必须大于 0</b> 时零价兜底<b>生效</b>（起价为 ¥0 的商品卡强制显示 ¥{{ form.min_price_floor }}/天）；
          切到 <b>允许为 0</b> 时自动<b>关闭</b>，¥0 照实展示。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">零价兜底（价格为 0 时显示为 元/天）</label>
        <input
          class="input"
          type="number" min="0" step="0.01"
          style="width:160px"
          v-model.number="form.min_price_floor"
        />
        <div class="form-hint">
          「保险/保护」逻辑：正常租赁模式下，商品起价**恰好为 ¥0** 时，接口强制返回此值（默认 20），
          避免漏配 / 异常导致商品卡出现 ¥0 起价。<b>只替换 0，不影响其它价格</b>（如 ¥13.5 仍原样显示）。<br>
          <b>仅在上方「租金可为 0」= 必须大于 0 时生效</b>；切到「允许为 0」（租押分离）会自动停用，
          让 ¥0 如实展示。修改后**立即生效**，无需重存商品。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">光影库存系统 · 特权 Token</label>
        <input class="input mono" type="text" v-model.trim="form.inventory_api_token" placeholder="粘贴 boss 在光影小程序设置页生成的特权Token" />
        <div class="form-hint">
          Token 由光影系统 boss 在小程序「设置」页生成并复制到这里；配置后发货填货号时自动加载商品卡片。
          光影侧删除该 Token 后立即失效。留空 = 不对接。
        </div>
      </div>

      <div class="form-field">
        <label class="form-label">发货时货号</label>
        <div class="seg-row">
          <label class="seg">
            <input type="radio" :value="false" v-model="form.ship_huohao_required" />
            <span>选填（默认）</span>
          </label>
          <label class="seg">
            <input type="radio" :value="true" v-model="form.ship_huohao_required" />
            <span>必填</span>
          </label>
        </div>
        <div class="form-hint">
          控制发货弹窗中「货号」字段是否必填。必填时运营不填货号无法提交发货。
        </div>
      </div>

      <div class="form-field danger">
        <label class="form-label">支付宝 / 小程序 APPID</label>
        <input class="input mono" type="text" v-model.trim="form.alipay_app_id" placeholder="如 2021000000000000" />
        <div class="form-hint danger-hint">
          ⚠️ 高危：改后下一次 freeze/query 立即用新 APPID。前提：
          <ol>
            <li>新 APPID 在开放平台已签约信用借还产品 + 已配公钥</li>
            <li>本机 <code>rsa_keys/app_private_key.pem</code> 是新 APPID 对应的私钥</li>
            <li>小程序前端 <code>qianduan/mini.project.json</code> 也要手动改成同一 APPID</li>
          </ol>
          不满足以上条件改了会导致全平台 freeze/query/notify 都签名失败。
        </div>
      </div>

    </div>

    <div v-if="msg" :class="['toast', msg.kind]">{{ msg.text }}</div>
  </div>
</template>

<script>
const { ref, reactive, inject, computed, onMounted } = Vue;

export default {
  setup() {
    const api = inject('api');
    const auth = inject('auth');
    const isAdmin = computed(() => auth.state.staff?.role === 'admin');
    const loading = ref(true);
    const saving = ref(false);
    const original = ref({});
    const form = reactive({
      ship_free_days:       3,
      service_phone:        '',
      company_name:         '',
      logo_url:             '',
      alipay_app_id:        '',
      freeze_includes_rent: true,
      allow_manual_date_pick: true,
      allow_zero_rent:        false,
      min_price_floor:        20,
      inventory_api_token:    '',
      ship_huohao_required:   false,
    });
    const msg = ref(null);
    const logoUploading = ref(false);

    // 相对路径补成可预览的绝对地址（后台与后端同域，/ 开头直接可用）
    const absUrl = (u) => {
      if (!u) return '';
      if (/^(https?:\/\/|data:)/.test(u)) return u;
      return u;   // 同域，相对路径浏览器能直接加载
    };
    const onLogoPick = async (e) => {
      const f = (e.target.files || [])[0];
      e.target.value = '';
      if (!f) return;
      logoUploading.value = true;
      try {
        const r = await api.upload(f);
        form.logo_url = r.url;   // 存相对路径
      } catch (err) {
        alert(err.message || '上传失败');
      } finally {
        logoUploading.value = false;
      }
    };

    const dirty = computed(() =>
      Object.keys(form).some(k => form[k] !== original.value[k])
    );

    const reload = async () => {
      if (!isAdmin.value) { loading.value = false; return; }
      loading.value = true;
      msg.value = null;
      try {
        const s = await api.getSettings();
        original.value = { ...s };
        Object.assign(form, s);
      } catch (e) {
        msg.value = { kind: 'err', text: e.message || '加载失败' };
      } finally {
        loading.value = false;
      }
    };

    const save = async () => {
      // 只 PUT 实际改过的字段，便于后端审计
      const patch = {};
      for (const k of Object.keys(form)) {
        if (form[k] !== original.value[k]) patch[k] = form[k];
      }
      if (!Object.keys(patch).length) return;

      // APPID 改动必须确认
      if ('alipay_app_id' in patch) {
        const ok = confirm(
          `确认把支付宝 APPID 改为：\n\n  ${patch.alipay_app_id}\n\n` +
          `必须同时：\n` +
          `① 新 APPID 在开放平台已签约信用借还+配密钥\n` +
          `② 本机 rsa_keys/app_private_key.pem 已替换\n` +
          `③ qianduan/mini.project.json 也已改\n\n` +
          `继续？`
        );
        if (!ok) return;
      }

      saving.value = true;
      msg.value = null;
      try {
        const s = await api.updateSettings(patch);
        original.value = { ...s };
        Object.assign(form, s);
        msg.value = { kind: 'ok', text: '已保存' };
        setTimeout(() => { msg.value = null; }, 2500);
      } catch (e) {
        msg.value = { kind: 'err', text: e.message || '保存失败' };
      } finally {
        saving.value = false;
      }
    };

    onMounted(reload);
    return { auth, isAdmin, loading, saving, form, dirty, msg, reload, save, logoUploading, onLogoPick, absUrl };
  },
};
</script>

<style scoped>
/* LOGO 上传 */
.logo-edit { display: flex; align-items: center; gap: 14px; }
.logo-preview {
  width: 72px; height: 72px; flex-shrink: 0;
  border: 1px solid var(--line, #e5e8ee); border-radius: 12px;
  overflow: hidden; background: #fafbfd;
  display: flex; align-items: center; justify-content: center;
}
.logo-preview img { width: 100%; height: 100%; object-fit: contain; }
.logo-ph { font-size: 12px; color: #9aa4b2; }
.logo-ops { display: flex; gap: 8px; }
.logo-ops .btn { cursor: pointer; }

.form-grid {
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 16px 0 24px;
  max-width: 640px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.form-label {
  font-size: 13px;
  color: #1a1f2e;
  font-weight: 500;
}
.input {
  height: 36px;
  border: 1px solid #d9dee7;
  border-radius: 4px;
  padding: 0 10px;
  font-size: 13px;
}
.input.mono {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
}
.input:focus { border-color: #4d8dff; outline: none; }
.seg-row {
  display: flex; gap: 16px; flex-wrap: wrap;
  margin-top: 2px;
}
.seg {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  border: 1px solid #d9dee7;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  background: #fff;
}
.seg input[type='radio'] { accent-color: #4d8dff; }
.seg:hover { border-color: #4d8dff; }
.form-hint {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.55;
}
.form-field.danger .form-label::after {
  content: '高危';
  display: inline-block;
  margin-left: 8px;
  padding: 1px 6px;
  font-size: 10px;
  background: #fdecea;
  color: #c0260b;
  border-radius: 3px;
  vertical-align: middle;
}
.danger-hint {
  background: #fff8ee;
  border-left: 3px solid #f0a955;
  padding: 8px 12px;
  border-radius: 4px;
  color: #8a4f00;
}
.danger-hint ol { margin: 4px 0 0 18px; padding: 0; }
.danger-hint li { margin-bottom: 2px; }
.danger-hint code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 11px;
  background: #fff;
  padding: 1px 4px;
  border-radius: 2px;
}
.toast {
  position: fixed;
  bottom: 30px;
  right: 30px;
  padding: 10px 18px;
  border-radius: 4px;
  font-size: 13px;
  box-shadow: 0 4px 14px rgba(0,0,0,0.12);
  z-index: 50;
}
.toast.ok  { background: #e8f7ee; color: #2a7942; border: 1px solid #c8e8d3; }
.toast.err { background: #fdecea; color: #c0260b; border: 1px solid #f5c2bd; }

.forbid {
  text-align: center;
  padding: 80px 30px;
}
.forbid-ico { font-size: 56px; line-height: 1; margin-bottom: 14px; }
.forbid-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 10px;
  color: #1a1f2e;
}
.forbid-sub {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.7;
}
.forbid-sub code {
  font-family: ui-monospace, Menlo, monospace;
  font-size: 12px;
  background: #f3f5f9;
  padding: 1px 6px;
  border-radius: 3px;
}
</style>
</content>
</invoke>