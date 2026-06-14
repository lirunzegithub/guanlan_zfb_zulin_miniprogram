<template>
  <div class="card">
    <div class="toolbar">
      <div class="card-title">分类设置</div>
      <button class="btn" @click="openNew">＋ 新增分类</button>
    </div>
    <table class="table">
      <thead>
        <tr>
          <th style="width:60px">ID</th>
          <th>名称</th>
          <th style="width:120px">父级</th>
          <th style="width:90px">排序</th>
          <th style="width:160px">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in list" :key="c.id">
          <td>{{ c.id }}</td>
          <td><strong>{{ c.name }}</strong></td>
          <td>{{ c.parent_id || '-' }}</td>
          <td>{{ c.sort }}</td>
          <td>
            <button class="btn-link" @click="openEdit(c)">编辑</button>
            <button class="btn-link danger" @click="remove(c)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !list.length"><td colspan="5" class="empty">暂无数据</td></tr>
        <tr v-if="loading"><td colspan="5" class="loading">加载中...</td></tr>
      </tbody>
    </table>
  </div>

  <div v-if="modal" class="modal-mask" @click.self="modal = null">
    <div class="modal">
      <div class="modal-h">{{ form.id ? '编辑分类' : '新增分类' }}</div>
      <div class="modal-body">
        <div class="field">
          <div class="label">名称 *</div>
          <input class="input" v-model="form.name" />
        </div>
        <div class="row" style="gap:12px">
          <div class="field" style="flex:1">
            <div class="label">父级 parent_id</div>
            <input type="number" class="input" v-model.number="form.parent_id" placeholder="0 = 顶层" />
          </div>
          <div class="field" style="width:120px">
            <div class="label">排序</div>
            <input type="number" class="input" v-model.number="form.sort" />
          </div>
        </div>
        <div class="field">
          <div class="label">描述</div>
          <input class="input" v-model="form.description" />
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

    const fetch = async () => {
      loading.value = true;
      try { const r = await api.list('categories'); list.value = r.list; }
      finally { loading.value = false; }
    };

    const openNew = () => {
      form.value = { name: '', parent_id: 0, description: '', sort: 0 };
      modal.value = true;
    };
    const openEdit = (c) => { form.value = { ...c }; modal.value = true; };

    const save = async () => {
      if (!form.value.name?.trim()) { alert('名称必填'); return; }
      saving.value = true;
      try {
        if (form.value.id) await api.update('categories', form.value.id, form.value);
        else await api.create('categories', form.value);
        modal.value = null;
        await fetch();
      } catch (e) { alert(e.message); }
      finally { saving.value = false; }
    };

    const remove = async (c) => {
      if (!confirm(`确认删除分类「${c.name}」？`)) return;
      try { await api.remove('categories', c.id); await fetch(); }
      catch (e) { alert(e.message); }
    };

    onMounted(fetch);
    return { list, loading, modal, form, saving, openNew, openEdit, save, remove };
  }
};
</script>
