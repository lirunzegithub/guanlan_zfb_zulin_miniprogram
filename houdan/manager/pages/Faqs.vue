<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">常见问题</div>
      <button class="btn" @click="openNew">＋ 新增问答</button>
    </div>
    <div class="muted small" style="padding: 0 16px 12px">
      问答将展示在小程序「客服中心 → 常见问题」处；sort 越小越靠前，相同时按 ID。
    </div>
    <table class="table">
      <thead>
        <tr>
          <th style="width:70px">ID</th>
          <th style="width:80px">排序</th>
          <th style="width:38%">问题</th>
          <th>答案预览</th>
          <th style="width:140px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="f in list" :key="f.id">
          <td>{{ f.id }}</td>
          <td>{{ f.sort }}</td>
          <td><strong>{{ f.q }}</strong></td>
          <td><div class="faq-preview">{{ f.a }}</div></td>
          <td>
            <button class="btn-link" @click="openEdit(f)">编辑</button>
            <button class="btn-link danger" @click="remove(f)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="5" class="empty">暂无常见问题</td></tr>
        <tr v-if="loading"><td colspan="5" class="loading">加载中...</td></tr>
      </tbody>
    </table>
  </div>

  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal" style="width: 640px; max-width: 95vw">
      <div class="modal-h">{{ form.id ? '编辑问答' : '新增问答' }}</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">问题 *</div>
          <input class="input" v-model="form.q" placeholder="如：如何申请芝麻信用免押？" maxlength="80" />
          <div class="muted small">尽量短，60 字以内</div>
        </div>
        <div class="field">
          <div class="label">答案 *</div>
          <textarea
            class="input"
            v-model="form.a"
            rows="6"
            placeholder="详细回答；支持换行，前端按 white-space: pre-wrap 渲染"
            style="font-family: inherit; resize: vertical; min-height: 120px"
            maxlength="500"
          ></textarea>
          <div class="muted small">{{ (form.a || '').length }} / 500</div>
        </div>
        <div class="field" style="max-width: 200px">
          <div class="label">排序 sort</div>
          <input type="number" class="input" v-model.number="form.sort" />
          <div class="muted small">越小越靠前。建议步长 10 留扩展。</div>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn btn-ghost" @click="modal = null">取消</button>
        <button class="btn" :disabled="saving || !canSave" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script>
const { ref, computed, inject, onMounted } = Vue;
export default {
  setup() {
    const api = inject('api');
    const list = ref([]);
    const loading = ref(true);
    const modal = ref(null);
    const form = ref({});
    const saving = ref(false);

    const canSave = computed(() =>
      !!(form.value.q || '').trim() && !!(form.value.a || '').trim()
    );

    const fetch = async () => {
      loading.value = true;
      try {
        const r = await api.list('faqs');
        // 按 sort 升序展示，与小程序前端一致
        list.value = (r.list || []).slice().sort((a, b) => {
          const sa = Number(a.sort || 0), sb = Number(b.sort || 0);
          if (sa !== sb) return sa - sb;
          return Number(a.id || 0) - Number(b.id || 0);
        });
      } finally { loading.value = false; }
    };

    const _nextSort = () => {
      // 自动给个比当前最大值大 10 的 sort，避免新条目排在前面
      const max = list.value.reduce((m, x) => Math.max(m, Number(x.sort || 0)), 0);
      return max + 10;
    };

    const openNew = () => {
      form.value = { q: '', a: '', sort: _nextSort() };
      modal.value = true;
    };
    const openEdit = (f) => { form.value = { ...f }; modal.value = true; };

    const save = async () => {
      if (!canSave.value) { alert('问题和答案都不能为空'); return; }
      saving.value = true;
      try {
        const body = {
          q:    (form.value.q || '').trim(),
          a:    (form.value.a || '').trim(),
          sort: Number(form.value.sort || 0),
        };
        if (form.value.id) await api.update('faqs', form.value.id, body);
        else                await api.create('faqs', body);
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    const remove = async (f) => {
      if (!confirm(`确认删除问答「${f.q}」？\n删除后小程序不再展示，操作不可撤销。`)) return;
      try { await api.remove('faqs', f.id); await fetch(); }
      catch (e) { alert(e.message); }
    };

    onMounted(fetch);
    return { list, loading, modal, form, saving, canSave, openNew, openEdit, save, remove };
  }
};
</script>

<style scoped>
.faq-preview {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-all;
}
.small { font-size: 12px; }
</style>
